# SPDX-License-Identifier: Apache-2.0
"""DUT wrapper generator (spec §5.2): one ``xut_dut`` per test configuration.

Every runner (xsim, Icarus, Verilator, the synthesis flows, the hardware harness)
drives the same flat interface::

    module xut_dut (input wire [NCLK-1:0] clk, input wire [NIN-1:0] in_vec,
                    output wire [NOUT-1:0] out_vec);

around exactly one primitive instance, and reads the same ``xut_dut.map.json``
(``format: "xut-map 1"``) recording which primitive port bit sits on which vector
bit, with its §5.1 class. Rules:

- Ports are taken in catalog order. ``clock``-class inputs go to ``clk``, other
  inputs to ``in_vec``, outputs to ``out_vec``; a port's LSB takes the lowest free
  bit. An ``inout`` port P adds P's ``drive_en`` bits, then its ``drive_val`` bits,
  to ``in_vec`` and its ``obs`` bits to ``out_vec``.
- Vector widths are ``max(1, n)``; the map records the true ``n``.
- Only explicitly given attributes are rendered, as Verilog literals of the
  attribute's kind. The primitive's own defaults apply to the rest, while the golden
  model uses the *documented* defaults, so a UNISIM/UG953 default mismatch surfaces
  as a finding. A value is never coerced to fit: a value of the wrong kind or width
  raises ``WrapError``.
- ``clock_out`` ports need the clock observers of spec §5.4 (a later step) and are
  refused unless ``raw_clock_out`` (equivalence and portability smoke runs only).
  ``drp`` and ``pad`` ports are wired like ``data``; the map records their class.
- The instance carries ``(* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE", keep *)``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from xut.catalog.model import CatalogEntry, is_enumerated
from xut.catalog.portclass import default_class
from xut.catalog.unisim import HdlModule
from xut.errors import XutError
from xut.formats.common import is_cfg

MAP_FORMAT = "xut-map 1"
HEADER = "// SPDX-License-Identifier: Apache-2.0\n"
KEEP_ATTRS = '(* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE", keep *)'

#: The wrapper signal each map vector lives on.
VEC_SIGNAL = {"clk": "clk", "in": "in_vec", "out": "out_vec"}
#: §5.1 classes the wrapper accepts for each port direction.
_CLASSES_FOR = {
    "input": frozenset({"clock", "async", "gate", "data", "pad", "drp"}),
    "output": frozenset({"data", "clock_out", "pad", "drp"}),
    "inout": frozenset({"inout"}),
}
_ROLES = frozenset({"", "drive_en", "drive_val", "obs"})
_INT32 = (-(2**31), 2**31 - 1)


class WrapError(XutError, ValueError):
    """A configuration the wrapper cannot realise, or a malformed map.json."""


@dataclass(frozen=True)
class PortSpec:
    name: str
    direction: str  # input | output | inout
    width: int
    cls: str  # spec §5.1 class


@dataclass(frozen=True)
class DutSpec:
    prim: str
    family: str
    cfg: str
    ports: tuple[PortSpec, ...]
    attrs: tuple[tuple[str, str], ...]  # (name, Verilog literal), catalog order
    raw_clock_out: bool = False
    min_event_gap_ps: int | None = None  # catalog override; None = validate's default


@dataclass(frozen=True)
class Bit:
    vec: str  # clk | in | out
    bit: int  # position in the vector
    port: str
    index: int  # bit of the port
    cls: str
    role: str = ""  # "" | drive_en | drive_val | obs


_MAP_KEYS = ("prim", "family", "cfg", "attrs", "nclk", "nin", "nout", "bits", "min_event_gap_ps")
_BIT_KEYS = tuple(f.name for f in fields(Bit))


@dataclass
class DutMap:
    prim: str
    family: str
    cfg: str
    attrs: dict[str, str]
    nclk: int
    nin: int
    nout: int
    bits: list[Bit] = field(default_factory=list)
    #: The primitive's catalog ``min_event_gap_ps`` (None: xut.validate.MIN_SEP_PS).
    min_event_gap_ps: int | None = None

    def of(self, vec: str) -> list[Bit]:
        """The bits of vector ``vec`` (clk | in | out), in bit order."""
        if vec not in VEC_SIGNAL:
            raise WrapError(f"unknown vector {vec!r} (expected clk, in or out)")
        return [b for b in self.bits if b.vec == vec]

    def port_bits(self, vec: str, port: str, role: str = "") -> list[Bit]:
        """The bits of ``port`` (with ``role``) on vector ``vec``, LSB first."""
        return [b for b in self.of(vec) if b.port == port and b.role == role]

    def clock_name(self, port: str) -> str:
        """``clk<N>``, the .xvec name of clock input ``port``."""
        bits = self.port_bits("clk", port)
        if len(bits) != 1:
            clocks = [b.port for b in self.of("clk")]
            raise WrapError(f"{self.prim}.{port} is not a clock input (clocks: {clocks})")
        return f"clk{bits[0].bit}"

    def clock_port(self, name: str) -> str:
        """The primitive port behind .xvec clock ``name`` (``clk<N>``)."""
        m = re.fullmatch(r"clk(\d+)", name)
        if not m or int(m.group(1)) >= self.nclk:
            raise WrapError(f"{self.prim}: no clock {name!r} (nclk={self.nclk})")
        return self.of("clk")[int(m.group(1))].port

    def in_ports(self) -> list[str]:
        """Plain input ports on ``in_vec`` (inout drive bits excluded), in map order."""
        return list(dict.fromkeys(b.port for b in self.of("in") if b.role == ""))

    def out_ports(self) -> list[str]:
        """Ports observed on ``out_vec`` (outputs and inout ``obs``), in map order."""
        return list(dict.fromkeys(b.port for b in self.of("out")))

    def cls_of(self, port: str) -> str:
        """The §5.1 class of ``port``."""
        for b in self.bits:
            if b.port == port:
                return b.cls
        raise WrapError(f"{self.prim}: no port {port!r} in the map")

    def to_json(self) -> str:
        return json.dumps({"format": MAP_FORMAT, **asdict(self)}, indent=1) + "\n"

    @classmethod
    def from_json(cls, text: str) -> DutMap:
        """Parse and check a map: exact keys, and each vector's bits numbered 0..n-1."""
        try:
            d = json.loads(text)
        except json.JSONDecodeError as e:
            raise WrapError(f"map.json: invalid JSON: {e}") from e
        if not isinstance(d, dict) or d.pop("format", None) != MAP_FORMAT:
            raise WrapError(f"map.json: not an {MAP_FORMAT} file")
        missing = [k for k in _MAP_KEYS if k not in d]
        unknown = sorted(set(d) - set(_MAP_KEYS))
        if missing or unknown:
            raise WrapError(f"map.json: missing key(s) {missing}, unknown key(s) {unknown}")
        if not isinstance(d["bits"], list) or not isinstance(d["attrs"], dict):
            raise WrapError("map.json: 'bits' must be a list and 'attrs' an object")
        _check_scalars(d)
        bits = []
        for i, b in enumerate(d["bits"]):
            if not isinstance(b, dict) or set(b) != set(_BIT_KEYS):
                raise WrapError(f"map.json: bit {i}: expected keys {list(_BIT_KEYS)}, got {b!r}")
            bits.append(Bit(**b))
        d["bits"] = bits
        m = cls(**d)
        _check_map(m)
        return m

    @classmethod
    def load(cls, path: Path) -> DutMap:
        path = Path(path)
        try:
            return cls.from_json(path.read_text())
        except WrapError as e:
            raise WrapError(f"{path}: {e}") from e


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_scalars(d: dict) -> None:
    for k in ("prim", "family", "cfg"):
        if not isinstance(d[k], str):
            raise WrapError(f"map.json: {k} must be a string, got {d[k]!r}")
    for k in ("nclk", "nin", "nout"):
        if not _is_int(d[k]) or d[k] < 0:
            raise WrapError(f"map.json: {k} must be a non-negative integer, got {d[k]!r}")
    g = d["min_event_gap_ps"]
    if g is not None and (not _is_int(g) or g < 1):
        raise WrapError(f"map.json: min_event_gap_ps must be null or >= 1, got {g!r}")
    for k, v in d["attrs"].items():
        if not isinstance(v, str):
            raise WrapError(f"map.json: attrs.{k} must be a Verilog literal string, got {v!r}")


def _check_map(m: DutMap) -> None:
    for b in m.bits:
        if b.vec not in VEC_SIGNAL or b.role not in _ROLES:
            raise WrapError(f"map.json: bad bit {b}")
    for vec, sig in VEC_SIGNAL.items():
        n = getattr(m, f"n{vec}")
        got = [b.bit for b in m.of(vec)]
        if len(got) != n:
            raise WrapError(f"map.json: {sig} has {len(got)} bits in the map but n{vec}={n}")
        if got != list(range(n)):
            raise WrapError(f"map.json: {sig} bits are not 0..{n - 1} in order: {got}")


# --- attribute values -----------------------------------------------------------------

_BASED = re.compile(r"^(\d+)?'([sS]?)([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)$")
_DECIMAL = re.compile(r"^[+-]?\d[\d_]*$")
_RADIX = {"b": 2, "o": 8, "d": 10, "h": 16}


def _parse_literal(lit: str) -> tuple[int | None, int]:
    """``(size or None, value)`` of a Verilog integer literal; x/z digits are refused."""
    s = lit.strip()
    m = _BASED.match(s)
    if m is None:
        if not _DECIMAL.match(s):
            raise WrapError(f"{lit!r} is not a Verilog integer literal")
        return None, int(s.replace("_", ""), 10)
    digits = m.group(4).replace("_", "")
    if re.search(r"[xXzZ?]", digits):
        raise WrapError(f"{lit!r} has x/z digits: attribute values must be fully defined")
    try:
        value = int(digits, _RADIX[m.group(3).lower()])
    except ValueError as e:
        raise WrapError(f"{lit!r}: invalid digits for its base") from e
    return (int(m.group(1)) if m.group(1) else None), value


def literal_value(lit: str | int) -> int:
    """The integer value of a Verilog literal (``8'hA5``, ``1'b1``, ``7``, ...)."""
    if isinstance(lit, bool):
        raise WrapError(f"{lit!r} is a bool, not a Verilog literal")
    if isinstance(lit, int):
        return lit
    return _parse_literal(str(lit))[1]


def _reject_type(ctx: str, value: object, allowed: tuple[type, ...]) -> None:
    if isinstance(value, bool):
        raise WrapError(f"{ctx}: bool {value!r} is ambiguous (YAML TRUE/1?); quote it")
    if not isinstance(value, allowed):
        raise WrapError(f"{ctx}: unsupported value {value!r} of type {type(value).__name__}")


def _render_bits(ctx: str, width: int, value: object) -> str:
    _reject_type(ctx, value, (int, str))
    if isinstance(value, int):
        if not 0 <= value < 2**width:
            raise WrapError(f"{ctx}: {value} does not fit {width} bits")
        if width == 1:
            return f"1'b{value}"
        return f"{width}'h{value:0{(width + 3) // 4}x}"
    lit = value.strip()
    try:
        size, v = _parse_literal(lit)
    except WrapError as e:
        raise WrapError(f"{ctx}: {e}") from e
    if size is None:
        raise WrapError(
            f"{ctx}: bit-vector value {lit!r} needs a sized literal (e.g. {width}'h...)"
        )
    if size != width:
        raise WrapError(f"{ctx}: literal {lit} has {size} bits, but the attribute is {width} bits")
    if v >= 2**width:
        raise WrapError(f"{ctx}: {lit} does not fit {width} bits")
    return lit


def _render_string(ctx: str, value: object) -> str:
    _reject_type(ctx, value, (int, str))
    s = str(value)
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    for bad, what in (('"', "quote"), ("\\", "backslash"), ("\n", "newline"), ("\r", "newline")):
        if bad in s:
            raise WrapError(f"{ctx}: string {value!r} contains a {what}")
    return f'"{s}"'


def _render_integer(ctx: str, value: object) -> str:
    _reject_type(ctx, value, (int, str))
    if isinstance(value, str):
        if not re.fullmatch(r"[+-]?\d+", value.strip()):
            raise WrapError(f"{ctx}: {value!r} is not a decimal integer")
        value = int(value.strip())
    if not _INT32[0] <= value <= _INT32[1]:
        raise WrapError(f"{ctx}: {value} does not fit a 32-bit integer parameter")
    return str(value)


def _render_real(ctx: str, value: object) -> str:
    _reject_type(ctx, value, (int, float, str))
    try:
        f = float(value)
    except ValueError as e:
        raise WrapError(f"{ctx}: {value!r} is not a real number") from e
    if not math.isfinite(f):
        raise WrapError(f"{ctx}: {value!r} is not a finite real number")
    return repr(f)  # always has a '.' or an exponent: a legal Verilog real literal


def render_attr(attr: dict, value: object) -> str:
    """``value`` as a Verilog parameter literal of ``attr``'s kind (bits/string/integer/real).

    Bit vectors take a Python int (rendered ``1'bN`` or zero-padded hex) or a sized
    literal of exactly the declared width, which is kept verbatim. Nothing is coerced:
    a value of the wrong kind, a bool, an x/z digit or an out-of-range value raises."""
    kind, name = attr["kind"], attr.get("name", "?")
    ctx = f"attribute {name}"
    if kind == "bits":
        return _render_bits(ctx, attr["width"], value)
    if kind == "string":
        if isinstance(value, float):
            raise WrapError(f"{ctx}: float {value!r} for a string attribute; quote it")
        return _render_string(ctx, value)
    if kind == "integer":
        if isinstance(value, float):
            raise WrapError(f"{ctx}: float {value!r} for an integer attribute")
        return _render_integer(ctx, value)
    if kind == "real":
        return _render_real(ctx, value)
    raise WrapError(f"{ctx}: unknown kind {kind!r}")


def _allowed_key(prim: str, attr: dict, lit: str) -> object:
    """Comparison key of a rendered literal or an ``allowed`` entry, by kind."""
    kind = attr["kind"]
    try:
        if kind == "bits":
            return literal_value(lit)
        if kind == "integer":
            return int(lit)
        if kind == "real":
            return float(lit)
    except (WrapError, ValueError) as e:
        raise WrapError(
            f"{prim}.{attr['name']}: cannot compare {lit!r} with the allowed list: {e}"
        ) from e
    return lit.strip('"')


def _check_allowed(prim: str, attr: dict, lit: str) -> None:
    allowed = attr.get("allowed") or []
    if not is_enumerated(allowed):
        return  # a range, a prose description, or nothing: advisory only
    keys = {_allowed_key(prim, attr, v) for v in allowed}
    if _allowed_key(prim, attr, lit) not in keys:
        raise WrapError(
            f"{prim}.{attr['name']}={lit} is not one of {allowed} (correct the catalog in "
            f"{prim}.overrides.yaml, or pass allow_illegal for an L0 rejection test)"
        )


def _render_attrs(
    prim: str, declared: list[dict], attrs: dict, allow_illegal: bool
) -> tuple[tuple[str, str], ...]:
    known = {a["name"] for a in declared}
    unknown = sorted(set(attrs) - known)
    if unknown:
        raise WrapError(f"{prim}: unknown attribute(s) {unknown}")
    out = []
    for a in declared:  # declaration (catalog) order
        if a["name"] in attrs:
            lit = render_attr(a, attrs[a["name"]])
            if not allow_illegal:
                _check_allowed(prim, a, lit)
            out.append((a["name"], lit))
    return tuple(out)


def _check_cfg(cfg: str) -> None:
    """A configuration name appears in Verilog comments, .xvec headers and as the
    ``<cfg>/`` prefix of .xtr labels, so it follows ``xut.formats.common.CFG``."""
    if not is_cfg(cfg):
        raise WrapError(f"configuration name {cfg!r} is not [A-Za-z0-9_.-]+")


def spec_from_catalog(
    entry: CatalogEntry,
    cfg: str,
    attrs: dict,
    *,
    allow_illegal: bool = False,
    raw_clock_out: bool = False,
) -> DutSpec:
    """The wrapper spec for catalog ``entry`` (overrides applied) with ``attrs`` set.

    ``allow_illegal`` permits values outside an enumerated ``allowed`` list (L0);
    ``raw_clock_out`` samples ``clock_out`` ports directly (smoke runs only)."""
    _check_cfg(cfg)
    rendered = _render_attrs(entry.name, entry.attributes, attrs, allow_illegal)
    ports = tuple(PortSpec(p["name"], p["direction"], p["width"], p["cls"]) for p in entry.ports)
    return DutSpec(
        entry.name, entry.family, cfg, ports, rendered, raw_clock_out, entry.min_event_gap_ps
    )


def spec_from_hdl(
    mod: HdlModule,
    cfg: str,
    attrs: dict,
    *,
    raw_clock_out: bool = False,
    family: str | None = None,
) -> DutSpec:
    """The wrapper spec for a parsed HDL module (no catalog entry): ports get their
    default §5.1 class, attributes are rendered by the parameter's kind. ``family``
    defaults to the one in ``docs/work-units.yaml``."""
    _check_cfg(cfg)
    if family is None:
        from xut.paths import repo_root
        from xut.workunits import load_family

        family = load_family(repo_root())
    declared = [{"name": p.name, "kind": p.kind, "width": p.width} for p in mod.params]
    rendered = _render_attrs(mod.name, declared, attrs, allow_illegal=True)
    ports = tuple(
        PortSpec(p.name, p.direction, p.width, default_class(mod.name, p.name, p.direction))
        for p in mod.ports
    )
    return DutSpec(mod.name, family, cfg, ports, rendered, raw_clock_out)


# --- map and Verilog ------------------------------------------------------------------


def _check_port(spec: DutSpec, p: PortSpec, seen: set[str]) -> None:
    where = f"{spec.prim}.{p.name}"
    if p.name in seen:
        raise WrapError(f"{where}: duplicate port")
    seen.add(p.name)
    if p.direction not in _CLASSES_FOR:
        raise WrapError(f"{where}: unknown direction {p.direction!r}")
    if p.cls not in _CLASSES_FOR[p.direction]:
        raise WrapError(f"{where}: {p.direction} port cannot have class {p.cls!r}")
    if not isinstance(p.width, int) or isinstance(p.width, bool) or p.width < 1:
        raise WrapError(f"{where}: bad width {p.width!r}")
    if p.cls == "clock_out" and not spec.raw_clock_out:
        raise WrapError(
            f"{where}: clock outputs need the clock observers of spec §5.4, which are "
            "not implemented yet (raw_clock_out samples them directly, for smoke runs only)"
        )


def build_map(spec: DutSpec) -> DutMap:
    """Assign every port bit a vector bit (module docstring rules)."""
    bits: list[Bit] = []
    n = {"clk": 0, "in": 0, "out": 0}
    seen: set[str] = set()

    def add(vec: str, p: PortSpec, role: str = "") -> None:
        for i in range(p.width):
            bits.append(Bit(vec, n[vec], p.name, i, p.cls, role))
            n[vec] += 1

    for p in spec.ports:
        _check_port(spec, p, seen)
        if p.direction == "inout":
            add("in", p, "drive_en")
            add("in", p, "drive_val")
            add("out", p, "obs")
        elif p.direction == "input":
            add("clk" if p.cls == "clock" else "in", p)
        else:
            add("out", p)
    return DutMap(
        spec.prim,
        spec.family,
        spec.cfg,
        dict(spec.attrs),
        n["clk"],
        n["in"],
        n["out"],
        bits,
        spec.min_event_gap_ps,
    )


def _slice(sig: str, idx: list[int]) -> str:
    if len(idx) == 1:
        return f"{sig}[{idx[0]}]"
    if idx == list(range(idx[0], idx[-1] + 1)):
        return f"{sig}[{idx[-1]}:{idx[0]}]"
    return "{" + ", ".join(f"{sig}[{i}]" for i in reversed(idx)) + "}"


def _comma_list(items: list[str], indent: str) -> list[str]:
    return [f"{indent}{s}" + ("," if i < len(items) - 1 else "") for i, s in enumerate(items)]


def render_wrapper(spec: DutSpec, m: DutMap) -> str:
    """``xut_dut.v`` for ``spec`` with bit assignment ``m`` (from ``build_map(spec)``)."""
    out = [
        HEADER.rstrip("\n"),
        f"// GENERATED by xut wrap: prim={spec.prim} cfg={spec.cfg}. Do not edit.",
        "`timescale 1ps / 1ps",
        "module xut_dut (",
        f"  input  wire [{max(1, m.nclk) - 1}:0] clk,",
        f"  input  wire [{max(1, m.nin) - 1}:0] in_vec,",
        f"  output wire [{max(1, m.nout) - 1}:0] out_vec",
        ");",
    ]
    conns = []
    for p in spec.ports:
        if p.direction == "inout":
            en = m.port_bits("in", p.name, "drive_en")
            val = m.port_bits("in", p.name, "drive_val")
            obs = m.port_bits("out", p.name, "obs")
            if not len(en) == len(val) == len(obs) == p.width:
                raise WrapError(f"{spec.prim}.{p.name}: map does not match the spec")
            out.append(f"  wire [{p.width - 1}:0] {p.name}__io;")
            for i in range(p.width):
                out.append(
                    f"  assign {p.name}__io[{i}] = in_vec[{en[i].bit}] ? "
                    f"in_vec[{val[i].bit}] : 1'bz;"
                )
                out.append(f"  assign out_vec[{obs[i].bit}] = {p.name}__io[{i}];")
            conns.append(f".{p.name}({p.name}__io)")
            continue
        vec = "out" if p.direction == "output" else ("clk" if p.cls == "clock" else "in")
        pb = m.port_bits(vec, p.name)
        if [b.index for b in pb] != list(range(p.width)):
            raise WrapError(f"{spec.prim}.{p.name}: map does not match the spec")
        conns.append(f".{p.name}({_slice(VEC_SIGNAL[vec], [b.bit for b in pb])})")
    if m.nout == 0:
        out.append("  assign out_vec = 1'b0;")
    out.append(f"  {KEEP_ATTRS}")
    if spec.attrs:
        out.append(f"  {spec.prim} #(")
        out += _comma_list([f".{k}({v})" for k, v in spec.attrs], "    ")
        out.append("  ) dut (")
    else:
        out.append(f"  {spec.prim} dut (")
    out += _comma_list(conns, "    ")
    out += ["  );", "endmodule"]
    return "\n".join(out) + "\n"


def render_cfg_vh(m: DutMap) -> str:
    """``xut_cfg.vh``: the vector widths as macros, for testbenches."""
    return (
        HEADER + f"// GENERATED by xut wrap: prim={m.prim} cfg={m.cfg}. Do not edit.\n"
        f"`define XUT_NCLK {max(1, m.nclk)}\n`define XUT_NIN {max(1, m.nin)}\n"
        f"`define XUT_NOUT {max(1, m.nout)}\n"
    )


def render_cocotb_top(m: DutMap) -> str:
    """cocotb has one toplevel, so glbl is instantiated here; UNISIM's ``glbl.GSR``
    resolves upward to this instance (IEEE 1364 upward name referencing)."""
    return (
        HEADER + f"// GENERATED by xut wrap --cocotb-top: prim={m.prim} cfg={m.cfg}. Do not edit.\n"
        '`timescale 1ps / 1ps\n`include "xut_cfg.vh"\n'
        "module xut_cocotb_top (\n"
        "  input  wire [`XUT_NCLK-1:0] clk,\n"
        "  input  wire [`XUT_NIN-1:0]  in_vec,\n"
        "  output wire [`XUT_NOUT-1:0] out_vec\n);\n"
        "  glbl glbl ();\n"
        "  xut_dut dut (.clk(clk), .in_vec(in_vec), .out_vec(out_vec));\n"
        "endmodule\n"
    )


def write_dut(spec: DutSpec, out_dir: Path, *, cocotb_top: bool = False) -> DutMap:
    """Write ``xut_dut.v``, ``xut_dut.map.json``, ``xut_cfg.vh`` (and
    ``xut_cocotb_top.v``) into ``out_dir``; return the map."""
    out_dir = Path(out_dir)
    m = build_map(spec)
    text = render_wrapper(spec, m)  # render everything before touching the disk
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "xut_dut.v").write_text(text)
    (out_dir / "xut_dut.map.json").write_text(m.to_json())
    (out_dir / "xut_cfg.vh").write_text(render_cfg_vh(m))
    if cocotb_top:
        (out_dir / "xut_cocotb_top.v").write_text(render_cocotb_top(m))
    return m
