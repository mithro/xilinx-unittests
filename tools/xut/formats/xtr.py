# SPDX-License-Identifier: Apache-2.0
"""The ``.xtr`` trace format (spec §5.3). Standard library only.

    file   := header NL { line NL }
    header := "# xut-trace 2" { SP key "=" token }
              keys: runner flow model seed, optionally kind(actual|expected) prim cfg ...
    line   := label { SP+ port "=" bits } [ SP+ "|" { SP+ port "=" provenance } ] [ "#" ... ]
    bits   := MSB-first chars of "01xz" (plus "-" = don't care in kind=expected); "_" ignored

Only the golden model writes "-" and provenance. A bit may be "-" only where
the model declares the documentation leaves it undefined.

Provenance is one whitespace-free token per port (``doc:375``,
``inferred:doc_silent_on_GSR_vs_CLR``). Following ``.xvec``'s conventions,
the writer never silently alters data to make it fit the line-oriented
format: a provenance value containing whitespace, ``#`` or ``|`` cannot be
represented on a trace line (those characters would be swallowed by comment
stripping or the ``|`` separator) and raises ``XtrError`` instead of being
mangled. Encode any such reason with ``_`` before it reaches this module.

Names follow the grammar of ``xut.formats.common``, shared with ``.xvec`` and
``xut wrap``: labels are ``[A-Za-z0-9_./-]+``, ports are Verilog identifiers, and a
``concat`` configuration prefix is a label without ``/``. ``Trace.add``, ``dumps``
and ``concat`` validate every label, port name, bit string, provenance tag and
header key/value, and raise ``XtrError`` on anything that could not be read back
exactly; nothing is ever silently altered.

Unlike ``.xvec``, ``.xtr`` has no quoting: a header value is one whitespace-free
token, and a ``#`` on a body line always starts a comment. That is safe because no
token a trace line may hold (label, port, bits, provenance) can contain ``#``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from xut.formats.common import FormatError, is_cfg, is_header_key, is_label, is_port

MAGIC = "xut-trace"
VERSION = 2
_HEADER = re.compile(r"^#\s*xut-trace\s+(\d+)\b(.*)$")
_PORT = re.compile(r"^([^=]*)=([01xz_-]+)$")
_PROV_BAD = re.compile(r"[\s#|]")
_HEADER_BAD = re.compile(r"[\s#]")
KINDS = ("actual", "expected")


class XtrError(FormatError):
    """Malformed or unrepresentable trace, with the 1-based line number when known."""


@dataclass(frozen=True)
class Mismatch:
    label: str
    port: str
    bit: int  # LSB = 0; -1 for whole-sample/port problems
    expected: str
    actual: str
    prov: str | None = None
    kind: str = "value"
    # value | missing-sample | extra-sample | missing-port | port-width | sample-order

    def __str__(self) -> str:
        where = f"{self.label} {self.port}" + (f"[{self.bit}]" if self.bit >= 0 else "")
        tag = f" ({self.prov})" if self.prov else ""
        return f"{where}: expected {self.expected}, got {self.actual}{tag} [{self.kind}]"


def _check_prov(tag: str) -> str:
    if not isinstance(tag, str) or not tag or _PROV_BAD.search(tag):
        raise XtrError(f"provenance {tag!r} must not contain whitespace, '#' or '|'")
    return tag


def _check_header(header: dict[str, str]) -> None:
    for k, v in header.items():
        if not is_header_key(k):
            raise XtrError(f"header key {k!r} is not [A-Za-z_][A-Za-z0-9_.]*")
        if not isinstance(v, str) or not v or _HEADER_BAD.search(v):
            raise XtrError(f"header {k}={v!r} cannot be represented (empty, whitespace or '#')")
    if header.get("kind", "actual") not in KINDS:
        raise XtrError(f"header kind={header['kind']!r} must be one of {KINDS}")


def _check_sample(
    label: str, values: dict[str, str], prov: dict[str, str] | None, kind: str
) -> None:
    if not is_label(label):
        raise XtrError(f"label {label!r} is not [A-Za-z0-9_./-]+")
    allowed = set("01xz") | ({"-"} if kind == "expected" else set())
    for port, bits in values.items():
        if not is_port(port):
            raise XtrError(f"{label}: port name {port!r} is not a Verilog identifier")
        if not isinstance(bits, str) or not bits or set(bits) - set("01xz-"):
            raise XtrError(f"{label} {port}: bits {bits!r} must be one or more of 01xz-")
        if set(bits) - allowed:
            raise XtrError(f"{label} {port}: '-' only allowed in kind=expected traces")
    for port, tag in (prov or {}).items():
        if port not in values:
            raise XtrError(f"{label}: provenance for {port!r}, which has no value")
        _check_prov(tag)


@dataclass
class Trace:
    header: dict[str, str]
    samples: dict[str, dict[str, str]] = field(default_factory=dict)
    prov: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.header.get("kind", "actual")

    def add(self, label: str, values: dict[str, str], prov: dict[str, str] | None = None) -> None:
        """Append sample ``label``; raises ``XtrError`` on anything unrepresentable."""
        if label in self.samples:
            raise XtrError(f"duplicate label {label!r}")
        _check_sample(label, values, prov, self.kind)
        self.samples[label] = dict(values)
        if prov:
            self.prov[label] = dict(prov)


def _group(bits: str) -> str:
    if len(bits) <= 4:
        return bits
    head = len(bits) % 4
    parts = ([bits[:head]] if head else []) + [bits[i : i + 4] for i in range(head, len(bits), 4)]
    return "_".join(parts)


def loads(text: str) -> Trace:
    lines = text.splitlines()
    m = _HEADER.match(lines[0]) if lines else None
    if not m or int(m.group(1)) != VERSION:
        raise XtrError("first line must be '# xut-trace 2 ...'", 1)
    header = {}
    for tok in m.group(2).split():
        k, eq, v = tok.partition("=")
        if not eq or k in header:
            raise XtrError(f"header token {tok!r} is not a new key=value", 1)
        header[k] = v
    try:
        _check_header(header)
    except XtrError as e:
        raise XtrError(str(e), 1) from e
    t = Trace(header)
    for n, raw in enumerate(lines[1:], start=2):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        values_part, _, prov_part = line.partition("|")
        toks = values_part.split()
        if not toks:
            raise XtrError("missing label", n)
        values = {}
        for tok in toks[1:]:
            pm = _PORT.match(tok)
            if not pm:
                raise XtrError(f"bad value {tok!r}", n)
            if pm.group(1) in values:
                raise XtrError(f"port {pm.group(1)!r} given twice", n)
            values[pm.group(1)] = pm.group(2).replace("_", "")
        prov = {}
        for tok in prov_part.split():
            port, eq, tag = tok.partition("=")
            if not eq or not tag or port in prov:
                raise XtrError(f"bad provenance token {tok!r}", n)
            prov[port] = tag
        try:
            t.add(toks[0], values, prov or None)
        except XtrError as e:
            raise XtrError(str(e), n) from e
    return t


def dumps(t: Trace) -> str:
    """The trace as text. Re-validates everything (samples may have been mutated in
    place since ``add``) and raises ``XtrError`` rather than write a file that would
    read back differently."""
    _check_header(t.header)
    out = [f"# {MAGIC} {VERSION}  " + " ".join(f"{k}={v}" for k, v in t.header.items())]
    for label, ports in t.samples.items():
        _check_sample(label, ports, t.prov.get(label), t.kind)
        line = label + "  " + " ".join(f"{p}={_group(b)}" for p, b in ports.items())
        if t.prov.get(label):
            line += "  | " + " ".join(f"{p}={v}" for p, v in t.prov[label].items())
        out.append(line)
    extra = sorted(set(t.prov) - set(t.samples))
    if extra:
        raise XtrError(f"provenance for label(s) {extra} with no sample")
    return "\n".join(out) + "\n"


def load(path: Path) -> Trace:
    return loads(Path(path).read_text())


def dump(t: Trace, path: Path) -> None:
    Path(path).write_text(dumps(t))


def _order_mismatch(a_order: list[str], b_order: list[str]) -> Mismatch | None:
    """Samples are points in simulated time, so a missing/extra sample aside, the
    labels common to both traces must appear in the same relative order in each.
    Returns the *first* offending label, with its 0-based position among the common
    labels in each trace's own order (``expected``/``actual``), or None if the
    common-label subsequences already agree. A label absent from one trace is not
    itself an order problem (that is `missing-sample`/`extra-sample`) -- only the
    labels present in both are compared here."""
    a_set, b_set = set(a_order), set(b_order)
    common_a = [lbl for lbl in a_order if lbl in b_set]
    common_b = [lbl for lbl in b_order if lbl in a_set]
    for i, lbl in enumerate(common_a):
        if common_b[i] != lbl:
            return Mismatch(lbl, "*", -1, str(i), str(common_b.index(lbl)), None, "sample-order")
    return None


def compare(expected: Trace, actual: Trace, *, x_observable: bool = True) -> list[Mismatch]:
    """Expected (golden, may hold '-') against one runner's actual trace."""
    out: list[Mismatch] = []
    for label, ports in expected.samples.items():
        got = actual.samples.get(label)
        if got is None:
            out.append(Mismatch(label, "*", -1, "sample", "missing", None, "missing-sample"))
            continue
        for port, exp in ports.items():
            prov = expected.prov.get(label, {}).get(port)
            act = got.get(port)
            if act is None:
                out.append(Mismatch(label, port, -1, exp, "missing", prov, "missing-port"))
                continue
            if len(act) != len(exp):
                out.append(Mismatch(label, port, -1, exp, act, prov, "port-width"))
                continue
            for i, (e, a) in enumerate(zip(reversed(exp), reversed(act), strict=True)):
                if e == "-" or (e in "xz" and not x_observable):
                    continue
                if e != a:
                    out.append(Mismatch(label, port, i, e, a, prov))
    for label in actual.samples:
        if label not in expected.samples:
            out.append(Mismatch(label, "*", -1, "none", "sample", None, "extra-sample"))
    if m := _order_mismatch(list(expected.samples), list(actual.samples)):
        out.append(m)
    return out


def diff(a: Trace, b: Trace, *, a_x: bool = True, b_x: bool = True) -> list[Mismatch]:
    """Two actual traces. A position where one side shows x/z and the other runner
    cannot observe x/z (2-state) is not comparable and is skipped (spec §5.6)."""
    out: list[Mismatch] = []
    for label in a.samples.keys() | b.samples.keys():
        pa, pb = a.samples.get(label), b.samples.get(label)
        if pa is None or pb is None:
            out.append(
                Mismatch(
                    label,
                    "*",
                    -1,
                    "present" if pa is not None else "missing",
                    "present" if pb is not None else "missing",
                    None,
                    "missing-sample",
                )
            )
            continue
        for port in pa.keys() | pb.keys():
            va, vb = pa.get(port), pb.get(port)
            if va is None or vb is None:
                out.append(
                    Mismatch(
                        label, port, -1, va or "missing", vb or "missing", None, "missing-port"
                    )
                )
                continue
            if len(va) != len(vb):
                out.append(Mismatch(label, port, -1, va, vb, None, "port-width"))
                continue
            for i, (ca, cb) in enumerate(zip(reversed(va), reversed(vb), strict=True)):
                if ca == cb or (ca in "xz" and not b_x) or (cb in "xz" and not a_x):
                    continue
                out.append(Mismatch(label, port, i, ca, cb))
    if m := _order_mismatch(list(a.samples), list(b.samples)):
        out.append(m)
    return sorted(out, key=lambda m: (m.label, m.port, m.bit))


def concat(parts: list[tuple[str, Trace]], header: dict[str, str]) -> Trace:
    """One trace of every configuration's samples, labelled ``<cfg>/<label>``."""
    _check_header(header)
    t = Trace(dict(header))
    for cfg, part in parts:
        if not is_cfg(cfg):
            raise XtrError(f"configuration name {cfg!r} is not [A-Za-z0-9_.-]+")
        for label, ports in part.samples.items():
            t.add(f"{cfg}/{label}", ports, part.prov.get(label))
    return t
