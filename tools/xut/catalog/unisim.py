# SPDX-License-Identifier: Apache-2.0
"""Extract the port/parameter interface of a UNISIM model with pyslang.

No preprocessor defines are passed, so parameters declared only under
``ifdef XIL_TIMING`` (LOC, MSGON, XON, ...) never appear. ``localparam``s are
dropped. Elaboration diagnostics (e.g. unresolved ``glbl.GSR`` references) are
ignored: only the module header is needed.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pyslang

_DIR = {"In": "input", "Out": "output", "InOut": "inout"}
_EK = pyslang.ast.ExpressionKind


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


def _is_string_literal(p) -> bool:
    """True if the parameter's default is a string literal (through implicit conversions)."""
    e = p.declaredType.initializer
    while e is not None and e.kind == _EK.Conversion:
        e = e.operand
    return e is not None and e.kind == _EK.StringLiteral


def _render_bits(v: pyslang.SVInt) -> str:
    """Verilog literal: binary for 1-bit values, hex otherwise (e.g. 1'b0, 256'h0)."""
    base = pyslang.LiteralBase.Binary if v.bitWidth == 1 else pyslang.LiteralBase.Hex
    return v.toString(base, True)


def _param(p) -> HdlParam:
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
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    comp = pyslang.ast.Compilation()
    comp.addSyntaxTree(tree)
    inst = next((i for i in comp.getRoot().topInstances if i.name == name), None)
    if inst is None:
        raise ValueError(f"module {name} not found as a top-level module in {path}")
    body = inst.body
    mod = HdlModule(name=name, source=path)
    for p in body.portList:
        direction = _DIR[str(p.direction).rsplit(".", 1)[-1]]
        mod.ports.append(HdlPort(p.name, direction, p.type.bitWidth))
    for p in body.parameters:
        if p.isLocalParam:
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
