# SPDX-License-Identifier: Apache-2.0
"""The z-compare rewrite (ruling S38, spec §6.2 rev 3.5): the second rewrite of
``xut verilatorize``.

Many UNISIM models default an unconnected input pin by comparing it with z, for example
``if (CE || (CE === 1'bz))`` in FDRE. Verilator 5.048 cannot build that below the top
module: V3Tristate lowers the comparison into a check of the port's enable, which makes the
input a tristate, and the instance pin then needs an ``__out`` variable an input does not
have ("Unsupported: tristate in top-level IO"; see ``xut.runners.verilator``).

Every comparison of an **input port** of the model (the file's primary module), whole or a
select of it, with a literal holding a z bit is replaced by its value for a driven input:

* ``P === <z literal>`` and ``<z literal> === P`` become ``1'b0``;
* ``P !== <z literal>`` and ``<z literal> !== P`` become ``1'b1``.

A driven input never holds a z bit, so the comparison is constant. That is exact when every
input is driven, which is the rewrite's validity condition: the runners and the
equivalence check refuse (``error``) a wrapper that leaves an input of such a model
unconnected, or a stimulus that drives z (``xut.runners.verilator``,
``xut.verilatorize.equiv``). The rewrite is applied unconditionally, never under
``ifdef VERILATOR``: Icarus (``iverilog-vz`` and the equivalence check against the original)
runs exactly the text Verilator compiles, so the existing oracle proves it.

Anything else is refused with ``TransformError`` (never skipped): a z-literal comparison
of an ``inout``/``output`` port, of an internal net, of an expression, of a name a local
declaration shadows, or in any module but the primary one; and ``==``/``!=``/``==?``/
``!=?`` or a ``case`` item with a z literal. It works on the syntax tree, so every generate
branch is covered. Code inside a preprocessor-disabled region (``ifdef XIL_TIMING``) is not
in the tree: ``leftover`` counts z-literal comparisons left in the text, and the driver
records them in the manifest's notes.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pyslang

from xut.verilatorize.analyze import TransformError, _walk_syntax

_SX = pyslang.syntax.SyntaxKind
#: comparison kind -> (operator, the constant a driven operand gives, or None: refused)
_CMP = {
    _SX.CaseEqualityExpression: ("===", "1'b0"),
    _SX.CaseInequalityExpression: ("!==", "1'b1"),
    _SX.EqualityExpression: ("==", None),
    _SX.InequalityExpression: ("!=", None),
    _SX.WildcardEqualityExpression: ("==?", None),
    _SX.WildcardInequalityExpression: ("!=?", None),
}
_SCOPES = {
    _SX.GenerateBlock,
    _SX.LoopGenerate,
    _SX.SequentialBlockStatement,
    _SX.ParallelBlockStatement,
    _SX.TaskDeclaration,
    _SX.FunctionDeclaration,
}
#: a z-literal comparison as text (for what the syntax tree cannot see: ``leftover``)
_ZLIT = r"(?:\d*\s*'s?[bBoOhH]\s*[0-9a-fA-FxXzZ_?]*[zZ?]|'[zZ]\b)"
_TEXT = re.compile(rf"[!=]==?\s*{_ZLIT}|{_ZLIT}\s*[!=]==?")
REWRITE = "zcmp"


@dataclass(frozen=True)
class ZCompare:
    start: int  # byte offsets of the comparison expression
    end: int
    op: str
    port: str
    line: int
    const: str


def _unparen(n: pyslang.syntax.SyntaxNode) -> pyslang.syntax.SyntaxNode:
    while n.kind == _SX.ParenthesizedExpression:
        n = n.expression
    return n


def _zlit(n: pyslang.syntax.SyntaxNode) -> bool:
    """A literal with a z (or ``?``) bit: ``1'bz``, ``4'b10z1``, ``'z``."""
    n = _unparen(n)
    if n.kind == _SX.IntegerVectorExpression:
        return bool(re.search(r"[zZ?]", n.value.rawText))
    if n.kind == _SX.UnbasedUnsizedLiteralExpression:
        return n.literal.rawText.lower() == "'z"
    return False


def _operand(n: pyslang.syntax.SyntaxNode) -> str | None:
    """The name a whole-name or select operand refers to, else None."""
    n = _unparen(n)
    if n.kind == _SX.IdentifierName:
        return n.identifier.valueText
    if n.kind == _SX.IdentifierSelectName:
        return n.identifier.valueText
    if n.kind == _SX.ElementSelectExpression:
        return _operand(n.left)
    return None


def _ports(mod: pyslang.syntax.SyntaxNode) -> dict[str, str]:
    """Port name -> direction (``input``, ``output``, ``inout``) of a module."""
    out: dict[str, str] = {}
    for n in _walk_syntax(mod):
        if n.kind == _SX.PortDeclaration:
            words = str(n.header).split()
            d = words[0] if words else "?"
            for dcl in n.declarators:
                if isinstance(dcl, pyslang.syntax.SyntaxNode) and dcl.kind == _SX.Declarator:
                    out[dcl.name.valueText] = d
        elif n.kind == _SX.ImplicitAnsiPort:
            words = str(n.header).split()
            out[n.declarator.name.valueText] = words[0] if words else "?"
    return out


def _shadowed(n: pyslang.syntax.SyntaxNode, name: str) -> bool:
    """``name`` is declared in a scope enclosing ``n`` below module level."""
    from xut.verilatorize.rewrite import _declared

    a = n.parent
    while a is not None and a.kind != _SX.ModuleDeclaration:
        if a.kind in _SCOPES and name in _declared(a):
            return True
        a = a.parent
    return False


def find(path: Path, model: str) -> list[ZCompare]:
    """Every z-literal comparison of ``path`` that the rewrite replaces; raises
    ``TransformError`` for any other z-literal comparison (module docstring)."""
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    raw = Path(path).read_bytes()
    out: list[ZCompare] = []

    def line(off: int) -> int:
        return raw.count(b"\n", 0, off) + 1

    for mod in _walk_syntax(tree.root):
        if mod.kind != _SX.ModuleDeclaration:
            continue
        name = mod.header.name.valueText
        ports = _ports(mod)
        for n in _walk_syntax(mod):
            if n.kind == _SX.StandardCaseItem and any(
                isinstance(e, pyslang.syntax.SyntaxNode) and _zlit(e) for e in n.expressions
            ):
                a = n.parent
                while a is not None and a.kind != _SX.CaseStatement:
                    a = a.parent
                if a is None or a.caseKeyword.rawText == "case":
                    raise TransformError(
                        model,
                        f"case item with a z literal at line "
                        f"{line(n.sourceRange.start.offset)} (module {name}): not a form the "
                        "z-compare rewrite handles (ruling S38)",
                    )
            if n.kind not in _CMP:
                continue
            left, right = _zlit(n.left), _zlit(n.right)
            if not (left or right):
                continue
            op, const = _CMP[n.kind]
            s, e = n.sourceRange.start.offset, n.sourceRange.end.offset
            where = f"`{raw[s:e].decode('utf-8', 'replace').strip()}` at line {line(s)}"
            if left and right:
                raise TransformError(model, f"z literal compared with a z literal: {where}")
            if const is None:
                raise TransformError(
                    model, f"`{op}` with a z literal: {where}; only ===/!== are rewritten (S38)"
                )
            if name != model:
                raise TransformError(
                    model,
                    f"z-literal comparison in module {name}, not the primary module {model}: "
                    f"{where} (ruling S38 rewrites the model's own input ports only)",
                )
            port = _operand(n.right if left else n.left)
            if port is None:
                raise TransformError(
                    model, f"z-literal comparison of an expression, not a port: {where}"
                )
            d = ports.get(port)
            if d != "input" or _shadowed(n, port):
                what = "internal net" if d is None or _shadowed(n, port) else f"{d} port"
                raise TransformError(
                    model,
                    f"z-literal comparison of {what} {port}: {where}; only an input port can "
                    "be rewritten (ruling S38)",
                )
            if not re.search(rb"[=!]==", raw[s:e]):  # a macro expansion: spans not the text
                raise TransformError(model, f"z-literal comparison not in the source text: {where}")
            out.append(ZCompare(s, e, op, port, line(s), const))
    return out


def apply(path: Path, model: str) -> tuple[bytes, list[ZCompare]]:
    """The bytes of ``path`` with every ``find`` comparison replaced by its constant."""
    raw = Path(path).read_bytes()
    found = find(path, model)
    out, pos = [], 0
    for z in sorted(found, key=lambda z: z.start):
        if z.start < pos:
            raise TransformError(model, f"nested z-literal comparisons at line {z.line}")
        out += [raw[pos : z.start], z.const.encode()]
        pos = z.end
    out.append(raw[pos:])
    return b"".join(out), found


def rewrite_text(text: str, model: str) -> tuple[str, list[ZCompare]]:
    """``apply`` for a model text (the shadow rewrite's output, or the original)."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / f"{model}.v"
        f.write_bytes(text.encode("utf-8", "surrogateescape"))
        data, found = apply(f, model)
    return data.decode("utf-8", "surrogateescape"), found


def leftover(text: str) -> int:
    """z-literal comparisons still in ``text`` (in preprocessor-disabled code)."""
    return len(_TEXT.findall(text))


# ---- the validity condition: every input driven (runners and the equivalence check) -------
def connected(m: object) -> set[str]:
    """The ports a wrapper map (``xut.wrap.DutMap``) drives: its clock and input bits."""
    return {b.port for b in m.bits if b.vec in ("clk", "in")}  # type: ignore[attr-defined]


def drives_z(vec: object) -> bool:
    """A stimulus (``xut.formats.xvec.Vec``) sets some input bit to z."""
    return any(e.op == "set" and "z" in e.value.lower() for e in vec.events)  # type: ignore[attr-defined]


def undriven_reason(model: str, missing: list[str]) -> str:
    return (
        f"input port(s) {', '.join(missing)} of {model} left unconnected by the wrapper: the "
        "z-compare rewrite (ruling S38) is valid only with every input driven"
    )


Z_STIMULUS = "stimulus drives z into a model with the z-compare rewrite (ruling S38)"
