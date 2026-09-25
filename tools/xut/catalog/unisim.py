# SPDX-License-Identifier: Apache-2.0
"""Extract the port/parameter interface of a UNISIM model with pyslang.

No preprocessor defines are passed, so parameters declared only under
``ifdef XIL_TIMING`` (LOC, MSGON, XON, ...) never appear. ``localparam``s are
dropped, as are the non-functional parameters in ``NON_FUNCTIONAL_PARAMS``.

Any Error-severity parse/elaboration diagnostic raises ``ValueError``, except
the narrow allowlist in ``_is_benign`` (things outside the module header that
slang cannot resolve when a model is compiled on its own).
"""

from dataclasses import dataclass, field
from pathlib import Path

import pyslang

_AD = pyslang.ast.ArgumentDirection
_DIR = {_AD.In: "input", _AD.Out: "output", _AD.InOut: "inout"}
_EK = pyslang.ast.ExpressionKind
_D = pyslang.Diags

# Placement (LOC) and timing-check message controls (MSGON, XON) are not
# functional attributes of a primitive. They are normally guarded by
# `ifdef XIL_TIMING, but some legacy models (DCM_ADV.v, DCM_SP.v) declare LOC
# unguarded, so they are filtered by name as well.
NON_FUNCTIONAL_PARAMS = frozenset({"LOC", "MSGON", "XON"})

# Error codes that are benign for header extraction. Each one arises only in
# the module body when the model is compiled standalone.
_BENIGN_CODES = frozenset(
    {
        # The body instantiates another library cell (retarget wrappers use LUT2
        # and similar cells, and some unisims wrap encrypted SIP_* cores).
        _D.UnknownModule,
        # A width mismatch on a `specify` parallel path (XADC.v, ICAPE2.v). This is
        # simulation timing only.
        _D.ParallelPathWidth,
        # A field width on `%m` in a $display message (MMCME5.v, X5PLL.v).
        _D.FormatSpecifierWidthNotAllowed,
    }
)


@dataclass(frozen=True)
class HdlPort:
    name: str
    direction: str  # "input" | "output" | "inout"
    width: int


@dataclass(frozen=True)
class HdlParam:
    name: str
    kind: str  # "string" | "integer" | "real" | "bits"
    width: int | None
    default: str | int | float


@dataclass
class HdlModule:
    name: str
    source: Path
    ports: list[HdlPort] = field(default_factory=list)
    params: list[HdlParam] = field(default_factory=list)


def _is_benign(d: pyslang.Diagnostic) -> bool:
    if d.code in _BENIGN_CODES:
        return True
    # The hierarchical reference to the simulator's global module (glbl.GSR,
    # glbl.GTS). glbl.v is not compiled with the model. Only the 'glbl' name is allowed.
    return d.code == _D.UndeclaredIdentifier and list(d.args) == ["glbl"]


def _is_string_literal(p: pyslang.ast.ParameterSymbol) -> bool:
    """True if the parameter's default is a string literal (through implicit conversions)."""
    e = p.declaredType.initializer
    while e is not None and e.kind == _EK.Conversion:
        e = e.operand
    return e is not None and e.kind == _EK.StringLiteral


def _render_bits(v: pyslang.SVInt) -> str:
    """Verilog literal: binary for 1-bit values, hex otherwise (e.g. 1'b0, 256'h0)."""
    base = pyslang.LiteralBase.Binary if v.bitWidth == 1 else pyslang.LiteralBase.Hex
    return v.toString(base, True)


def _param(p: pyslang.ast.ParameterSymbol) -> HdlParam:
    t, cv = p.type, p.value
    if t.isString or _is_string_literal(p):
        # Untyped string parameters become logic[8N-1:0]; decode back to text.
        return HdlParam(p.name, "string", None, cv.convertToStr().value)
    if t.isFloating:
        return HdlParam(p.name, "real", None, float(cv.value))
    if t.isPredefinedInteger or (t.isIntegral and t.isSigned):
        # `integer`/`int`, or an untyped parameter with an unsized integer default.
        return HdlParam(p.name, "integer", None, int(cv.value))
    return HdlParam(p.name, "bits", t.bitWidth, _render_bits(cv.value))


def parse_module(path: Path, name: str) -> HdlModule:
    """Parse module ``name`` from ``path`` and return its ports and user parameters."""
    try:
        tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
        comp = pyslang.ast.Compilation()
        comp.addSyntaxTree(tree)
        diags = [d for d in comp.getAllDiagnostics() if d.isError() and not _is_benign(d)]
    except FileNotFoundError:
        raise
    except Exception as e:
        raise ValueError(f"{path}: pyslang failed: {e}") from e
    if diags:
        codes = sorted({str(d.code) for d in diags})
        text = pyslang.DiagnosticEngine.reportAll(comp.sourceManager, diags)
        raise ValueError(f"{path}: {len(diags)} unexpected error(s) {codes}\n{text}")
    inst = next((i for i in comp.getRoot().topInstances if i.name == name), None)
    if inst is None:
        raise ValueError(f"module {name} not found as a top-level module in {path}")
    body = inst.body
    mod = HdlModule(name=name, source=path)
    for p in body.portList:
        mod.ports.append(HdlPort(p.name, _DIR[p.direction], p.type.bitWidth))
    for p in body.parameters:
        if p.isLocalParam or p.name in NON_FUNCTIONAL_PARAMS:
            continue
        mod.params.append(_param(p))
    return mod


def find_model(name: str, search: list[Path]) -> tuple[Path, str] | None:
    """Return ``(file, library_dir_name)`` for the first ``<name>.v`` in ``search``."""
    for d in search:
        f = d / f"{name}.v"
        if f.is_file():
            return f, d.name
    return None
