# SPDX-License-Identifier: Apache-2.0
"""AST analysis for `xut verilatorize` (spec §6.2).

Finds every procedurally-forced reg X (target of a procedural ``assign``) and:
  * the spans to rewrite: declaration identifier, ordinary lvalue writes,
    each ``assign X = e_k;`` and each ``deassign X;``;
  * its triggers: roots (primitive inputs or glbl.*) of the full transitive
    fan-in cone of the sensitivity lists of the blocks that force it. The cone
    crosses continuous assigns, gate primitives, same-file sub-instances,
    combinational logic and registered stages;
  * its enablers: clocks met while crossing registered stages (edge events of a
    block that the write itself does not read).

Every generate branch is analysed: `generate_configs` derives parameter overrides that
together elaborate every branch, and `analyze` takes the union over them.

Anything it cannot prove it handles raises TransformError naming the model. A signal in a
trigger cone whose driver cannot be resolved is always an error, never a dropped trigger.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pyslang
from pyslang import ast

from xut.catalog.unisim import _is_benign
from xut.errors import XutError

_SK, _EK, _TK, _SY = ast.StatementKind, ast.ExpressionKind, ast.TimingControlKind, ast.SymbolKind
_SX = pyslang.syntax.SyntaxKind
SyntaxNode, SyntaxTree = pyslang.syntax.SyntaxNode, pyslang.syntax.SyntaxTree
_AstNode = ast.Symbol | ast.Statement | ast.Expression | ast.TimingControl
_AD = ast.ArgumentDirection
_EDGES = (ast.EdgeKind.PosEdge, ast.EdgeKind.NegEdge, ast.EdgeKind.BothEdges)
_DELAYS = (_TK.Delay, _TK.Delay3, _TK.OneStepDelay, _TK.CycleDelay)
_SYNTAX_FORCE = {_SX.ProceduralAssignStatement, _SX.ProceduralDeassignStatement}
_CONSTANT_SYMBOLS = (_SY.Parameter, _SY.Specparam, _SY.EnumValue, _SY.Genvar)
_LOOPS = (
    _SK.ForLoop,
    _SK.RepeatLoop,
    _SK.WhileLoop,
    _SK.DoWhileLoop,
    _SK.ForeverLoop,
    _SK.ForeachLoop,
)
_NOOPS = (_SK.Empty, _SK.Disable, _SK.Return, _SK.Break, _SK.Continue)
# Gate primitives whose leading terminals are all outputs (buf/not may drive several).
_MULTI_OUT = ("buf", "not")
_LITERALS = {
    _SX.IntegerLiteralExpression,
    _SX.IntegerVectorExpression,
    _SX.StringLiteralExpression,
    _SX.RealLiteralExpression,
    _SX.UnbasedUnsizedLiteralExpression,
}
_RELATIONAL = {
    _SX.LessThanExpression,
    _SX.LessThanEqualExpression,
    _SX.GreaterThanExpression,
    _SX.GreaterThanEqualExpression,
}
_INTEGER_TYPES = {"integer": "signed [31:0]", "time": "[63:0]"}
_ONE_BIT_TYPE = re.compile(r"(?:(?:bit|logic|reg)\s*)?(?:\[\s*(\d+)\s*:\s*\1\s*\])?", re.S)


class TransformError(XutError):
    """The transform cannot prove it handles a construct of ``model`` (spec §6.2 rule 4)."""

    def __init__(self, model: str, msg: str) -> None:
        super().__init__(f"{model}: {msg}")
        self.model = model


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass
class ForcedReg:
    name: str
    dims: str  # declaration text between the type keyword and the name, e.g. "signed [4:1] "
    decl_name: Span
    decl_end: int
    is_port: bool
    overrides: list[tuple[Span, Span]] = field(default_factory=list)  # (statement, rhs)
    deassigns: list[Span] = field(default_factory=list)
    writes: set[Span] = field(default_factory=set)
    sensitivity: set[str] = field(default_factory=set)
    triggers: set[str] = field(default_factory=set)
    enablers: set[str] = field(default_factory=set)


@dataclass
class Analysis:
    model: str
    path: Path
    text: str
    endmodule: int
    forced: dict[str, ForcedReg]

    @property
    def triggers(self) -> list[str]:
        return sorted(set().union(*(f.triggers for f in self.forced.values())))

    @property
    def enablers(self) -> list[str]:
        en = set().union(*(f.enablers for f in self.forced.values()))
        return sorted(en - set(self.triggers))


@dataclass(frozen=True)
class _Driver:
    reads: frozenset[str]
    clocks: frozenset[str]


@dataclass(frozen=True)
class _Ctx:
    edges: frozenset[str]
    levels: frozenset[str]


class _Source:
    """A model's text, read without newline translation, and pyslang byte offsets mapped
    to ``str`` indices (the models are not all ASCII)."""

    def __init__(self, path: Path) -> None:
        self.text = Path(path).read_bytes().decode("utf-8", "surrogateescape")
        self._map: list[int] | None = None
        if not self.text.isascii():
            self._map = []
            for i, ch in enumerate(self.text):
                self._map += [i] * len(ch.encode("utf-8", "surrogateescape"))
            self._map.append(len(self.text))

    def char(self, byte_offset: int) -> int:
        return byte_offset if self._map is None else self._map[byte_offset]

    def line(self, byte_offset: int) -> int:
        return self.text.count("\n", 0, self.char(byte_offset)) + 1


# ---- syntax-level helpers ---------------------------------------------------------------------
def _children(node: SyntaxNode) -> Iterator[SyntaxNode]:
    for c in node:
        if isinstance(c, pyslang.syntax.SyntaxNode):
            yield c


def _nodes(lst: Iterable[object]) -> list[SyntaxNode]:
    """The nodes of a (separated) syntax list, without its separator tokens."""
    return [c for c in lst if isinstance(c, pyslang.syntax.SyntaxNode)]


def _walk_syntax(node: SyntaxNode) -> Iterator[SyntaxNode]:
    yield node
    for c in _children(node):
        yield from _walk_syntax(c)


def has_procedural_assign(path: Path) -> bool:
    """True if the file contains a procedural ``assign``/``deassign`` (syntax only)."""
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    return any(n.kind in _SYNTAX_FORCE for n in _walk_syntax(tree.root))


def _module_decl(tree: SyntaxTree, module: str) -> SyntaxNode:
    for n in _walk_syntax(tree.root):
        if n.kind == _SX.ModuleDeclaration and n.header.name.valueText == module:
            return n
    raise TransformError(module, "module declaration not found")


def _tokens(node: SyntaxNode) -> Iterator[pyslang.parsing.Token]:
    for c in node:
        if isinstance(c, pyslang.syntax.SyntaxNode):
            yield from _tokens(c)
        elif c is not None:
            yield c


def _plain(node: SyntaxNode) -> str:
    """The node's source text without its leading trivia (whitespace, comments)."""
    out: list[str] = []
    for i, t in enumerate(_tokens(node)):
        if i:
            out += [tr.getRawText() for tr in t.trivia]
        out.append(t.rawText)
    return "".join(out).strip()


def _param_decls(
    tree: SyntaxTree, module: str
) -> list[tuple[str, SyntaxNode | None, SyntaxNode | None, bool]]:
    """(name, type syntax, initializer expr, is_local) for every parameter of ``module``."""
    out = []
    for n in _walk_syntax(_module_decl(tree, module)):
        if n.kind == _SX.ParameterDeclaration:
            local = n.keyword.valueText == "localparam"
            for d in _nodes(n.declarators):
                init = d.initializer.expr if d.initializer is not None else None
                out.append((d.name.valueText, n.type, init, local))
    return out


def _module_parameters(tree: SyntaxTree, module: str) -> dict[str, str]:
    """Overridable parameter name -> default value text."""
    return {
        n: _plain(init)
        for n, _, init, local in _param_decls(tree, module)
        if not local and init is not None
    }


def _localparams(tree: SyntaxTree, module: str) -> dict[str, SyntaxNode]:
    return {
        n: init for n, _, init, local in _param_decls(tree, module) if local and init is not None
    }


def _is_one_bit(tree: SyntaxTree, module: str, name: str) -> bool:
    for n, typ, _, _ in _param_decls(tree, module):
        if n == name:
            t = _plain(typ) if typ is not None else ""
            return bool(t) and _ONE_BIT_TYPE.fullmatch(t) is not None
    return False


def _identifiers(node: SyntaxNode) -> set[str]:
    return {n.identifier.valueText for n in _walk_syntax(node) if n.kind == _SX.IdentifierName}


def _unparen(node: SyntaxNode) -> SyntaxNode:
    while node.kind == _SX.ParenthesizedExpression:
        node = node.expression
    return node


def _literals_compared_with(nodes: list[SyntaxNode], name: str, default: str) -> list[str]:
    """Literals that ``name`` is compared with (binary operators, or case items when the
    case expression is ``name``), plus the default; ``[]`` when there is none. A relational
    comparison with an unsized integer ``n`` adds ``n-1`` and ``n+1`` so both outcomes are
    reachable."""
    lits: list[str] = []

    def add(v: str) -> None:
        if v not in lits:
            lits.append(v)

    for root in nodes:
        for n in _walk_syntax(root):
            if not isinstance(n, pyslang.syntax.BinaryExpressionSyntax):
                continue
            left, right = _unparen(n.left), _unparen(n.right)
            for a, b in ((left, right), (right, left)):
                if (
                    a.kind == _SX.IdentifierName
                    and a.identifier.valueText == name
                    and b.kind in _LITERALS
                ):
                    v = _plain(b)
                    if n.kind in _RELATIONAL and re.fullmatch(r"\d+", v):
                        for k in (int(v) - 1, int(v), int(v) + 1):
                            if k >= 0:
                                add(str(k))
                    else:
                        add(v)
    return [default] + [v for v in lits if v != default] if lits else []


def _case_literals(case: SyntaxNode, name: str) -> list[str]:
    if (
        _unparen(case.condition).kind != _SX.IdentifierName
        or _unparen(case.condition).identifier.valueText != name
    ):
        return []
    return [
        _plain(e)
        for item in case.items
        if item.kind == _SX.StandardCaseItem
        for e in _nodes(item.expressions)
        if _unparen(e).kind in _LITERALS
    ]


@dataclass
class _GenConstruct:
    node: SyntaxNode  # the IfGenerate (head of an else-if chain) or CaseGenerate
    conds: list[SyntaxNode]  # condition expressions (every link of an else-if chain)
    arms: list[SyntaxNode]  # arm syntax nodes (each becomes a GenerateBlock when elaborated)


def _generate_constructs(tree: SyntaxTree, module: str) -> tuple[list[_GenConstruct], list[str]]:
    """Top-level generate if/case constructs of ``module`` and the text of any nested one."""
    constructs: list[_GenConstruct] = []
    nested: list[str] = []

    def visit(n: SyntaxNode, depth: int) -> None:
        if n.kind == _SX.IfGenerate:
            c = _GenConstruct(n, [], [])
            link = n
            while True:
                c.conds.append(link.condition)
                c.arms.append(link.block)
                visit(link.block, depth + 1)
                ec = link.elseClause
                if ec is None:
                    break
                if ec.clause.kind == _SX.IfGenerate:
                    link = ec.clause
                    continue
                c.arms.append(ec.clause)
                visit(ec.clause, depth + 1)
                break
            (nested if depth else constructs).append(c if not depth else _plain(c.conds[0]))
        elif n.kind == _SX.CaseGenerate:
            c = _GenConstruct(n, [n.condition], [])
            for item in n.items:
                c.conds += _nodes(item.expressions) if item.kind == _SX.StandardCaseItem else []
                c.arms.append(item.clause)
                visit(item.clause, depth + 1)
            (nested if depth else constructs).append(c if not depth else _plain(n.condition))
        else:
            for ch in _children(n):
                visit(ch, depth)

    visit(_module_decl(tree, module), 0)
    return constructs, nested


def _expand_localparams(nodes: list[SyntaxNode], local: dict[str, SyntaxNode]) -> list[SyntaxNode]:
    """The condition nodes plus the initializers of every localparam they name, transitively."""
    out, seen, work = list(nodes), set(), list(nodes)
    while work:
        for name in _identifiers(work.pop()):
            if name in local and name not in seen:
                seen.add(name)
                out.append(local[name])
                work.append(local[name])
    return out


def generate_configs(
    path: Path, module: str, choices: dict[str, list[str]] | None = None, limit: int = 64
) -> list[dict[str, str]]:
    """Parameter overrides that together elaborate every generate branch (review #3).

    Syntax-level: for each `if`/`case` generate construct (an else-if chain is one
    construct), take the module parameters its conditions name, directly or through
    localparams. Candidate values are `choices[name]` (the catalog's allowed values) when
    given; otherwise both values for a 1-bit parameter; otherwise every literal the
    conditions compare the parameter with, plus the default. Take the product per construct
    (other parameters at default), union over constructs, deduplicate, and put `{}` first.
    A generate if/case nested inside another raises (known limitation). Loop generates need
    nothing: every iteration is elaborated. Raises if a condition names a parameter with no
    candidates, or the total exceeds `limit`."""
    module_name = module
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    params = _module_parameters(tree, module_name)
    local = _localparams(tree, module_name)
    constructs, nested = _generate_constructs(tree, module_name)
    if nested:
        raise TransformError(
            module_name, f"nested generate conditions are not supported: `{nested[0]}`"
        )
    out: list[dict[str, str]] = [{}]
    for c in constructs:
        nodes = _expand_localparams(c.conds, local)
        names = sorted(set().union(*(_identifiers(n) for n in nodes)) & set(params))
        cands: dict[str, list[str]] = {}
        for n in names:
            lits = _literals_compared_with(nodes, n, params[n])
            if c.node.kind == _SX.CaseGenerate:
                extra = [v for v in _case_literals(c.node, n) if v not in lits]
                lits = (lits or [params[n]]) + extra if extra else lits
            cands[n] = (
                (choices or {}).get(n)
                or (["1'b0", "1'b1"] if _is_one_bit(tree, module_name, n) else None)
                or lits
            )
        empty = [n for n, v in cands.items() if not v]
        if empty:
            raise TransformError(
                module_name,
                f"cannot enumerate generate configurations: no "
                f"candidate values for {empty} in `{_plain(c.conds[0])}`",
            )
        for combo in itertools.product(*(cands[n] for n in names)):
            cfg = {n: v for n, v in zip(names, combo, strict=True) if v != params[n]}
            if cfg not in out:
                out.append(cfg)
    if len(out) > limit:
        raise TransformError(
            module_name, f"cannot enumerate generate configurations: {len(out)} > {limit}"
        )
    return out


# ---- elaborated-AST walker -------------------------------------------------------------------
class _Walker:
    def __init__(self, model: str, inst: ast.InstanceSymbol, src: _Source) -> None:
        self.model, self.inst, self.body, self.src = model, inst, inst.body, src
        self.text = src.text
        self.buffer = inst.body.location.buffer
        self.prefix = inst.body.hierarchicalPath + "."
        self.inputs = {p.name for p in self.body.portList if p.direction in (_AD.In, _AD.InOut)}
        self.forced_names: set[str] = set()
        self.drivers: dict[str, list[_Driver]] = defaultdict(list)
        self.opaque: set[str] = set()
        self.regs: dict[str, ForcedReg] = {}
        self.generate_blocks: set[int] = set()  # syntax offsets of elaborated generate blocks
        self._stack: list[str] = []  # hierarchical paths of the subroutines being entered

    # ---- helpers ---------------------------------------------------------------------------
    def err(self, msg: str) -> TransformError:
        return TransformError(self.model, msg)

    def key(self, sym: ast.Symbol) -> str:
        path = sym.hierarchicalPath
        return path[len(self.prefix) :] if path.startswith(self.prefix) else path

    def span(self, node: _AstNode) -> Span:
        r = node.sourceRange
        if r.start.buffer != self.buffer or r.end.buffer != self.buffer:
            own = r.end if r.end.buffer == self.buffer else r.start
            where = f" at line {self.src.line(own.offset)}" if own.buffer == self.buffer else ""
            raise self.err(
                f"construct{where} is inside a macro expansion or include; the transform "
                "only rewrites the model's own text"
            )
        return Span(self.src.char(r.start.offset), self.src.char(r.end.offset))

    def is_other_scope(self, n: _AstNode) -> bool:
        """An instance other than the model, or a generate block not elaborated here."""
        if n.kind == _SY.Instance:
            return n.hierarchicalPath != self.inst.hierarchicalPath
        if n.kind == _SY.GenerateBlock:
            if n.isUninstantiated:
                return True
            self.generate_blocks.add(n.syntax.sourceRange.start.offset)
        return False

    def reads(self, node: _AstNode, out: set[str]) -> set[str]:
        """Every non-constant name ``node`` reads, through called function bodies (whose own
        arguments and locals are not reads of the caller)."""

        def v(n: _AstNode) -> ast.VisitAction:
            k = n.kind
            if k in (_EK.NamedValue, _EK.HierarchicalValue):
                if n.symbol.kind not in _CONSTANT_SYMBOLS:
                    name = self.key(n.symbol)
                    if not any(name.startswith(s + ".") for s in self._stack):
                        out.add(name)
            elif k == _EK.Call and not n.isSystemCall:
                sub = self.key(n.subroutine)
                if sub not in self._stack:
                    self._stack.append(sub)
                    n.subroutine.body.visit(v)
                    self._stack.pop()
            return ast.VisitAction.Advance

        node.visit(v)
        return out

    def lvalues(self, e: ast.Expression) -> list[ast.Expression]:
        k = e.kind
        if k == _EK.NamedValue:
            return [e]
        if k == _EK.HierarchicalValue:
            return []
        if k in (_EK.ElementSelect, _EK.RangeSelect, _EK.MemberAccess):
            return self.lvalues(e.value)
        if k == _EK.Concatenation:
            return [n for op in e.operands for n in self.lvalues(op)]
        if k == _EK.Conversion:
            return self.lvalues(e.operand)
        if k == _EK.Assignment:  # output port / argument connections
            return self.lvalues(e.left)
        raise self.err(
            f"unsupported lvalue form {k.name} at line {self.src.line(e.sourceRange.start.offset)}"
        )

    def select_reads(self, e: ast.Expression, out: set[str]) -> None:
        k = e.kind
        if k == _EK.ElementSelect:
            self.reads(e.selector, out)
            self.select_reads(e.value, out)
        elif k == _EK.RangeSelect:
            self.reads(e.left, out)
            self.reads(e.right, out)
            self.select_reads(e.value, out)
        elif k == _EK.Concatenation:
            for op in e.operands:
                self.select_reads(op, out)

    def rvalue_names(self, stmt: ast.Statement) -> set[str]:
        """Names a statement reads (lvalue roots of its assignments excluded). The lvalue of
        a ``deassign`` counts as a read: its rewrite reads the reg."""
        lv: set[int] = set()
        names: list[tuple[str, int]] = []

        def v(n: _AstNode) -> ast.VisitAction:
            k = n.kind
            if k == _EK.Assignment:
                lv.update(x.sourceRange.start.offset for x in self.lvalues(n.left))
            elif k in (_EK.NamedValue, _EK.HierarchicalValue):
                names.append((self.key(n.symbol), n.sourceRange.start.offset))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return {name for name, off in names if off not in lv}

    def written_names(self, stmt: _AstNode) -> set[str]:
        out: set[str] = set()

        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind == _EK.Assignment:
                out.update(self.key(x.symbol) for x in self.lvalues(n.left))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return out

    def forced_in(self, stmt: ast.Statement) -> set[str]:
        out: set[str] = set()

        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind == _SK.ProceduralAssign and n.assignment.left.kind == _EK.NamedValue:
                out.add(self.key(n.assignment.left.symbol))
            elif n.kind == _SK.ProceduralDeassign and n.lvalue.kind == _EK.NamedValue:
                out.add(self.key(n.lvalue.symbol))
            return ast.VisitAction.Advance

        stmt.visit(v)
        return out

    # ---- pass 1: which regs are forced -----------------------------------------------------
    def prescan(self) -> None:
        def v(n: _AstNode) -> ast.VisitAction:
            if self.is_other_scope(n):
                return ast.VisitAction.Skip
            if n.kind == _SK.ProceduralAssign:
                if n.isForce:
                    raise self.err("force/release is not supported by the transform")
                if n.assignment.left.kind != _EK.NamedValue:
                    raise self.err(
                        f"procedural assign to a select or concatenation at line "
                        f"{self.src.line(n.sourceRange.start.offset)}"
                    )
                self.forced_names.add(self.key(n.assignment.left.symbol))
                self._reg(n.assignment.left.symbol)
            elif n.kind == _SK.ProceduralDeassign:
                if n.isRelease:
                    raise self.err("force/release is not supported by the transform")
                if n.lvalue.kind != _EK.NamedValue:
                    raise self.err(
                        f"procedural deassign of a select or concatenation at "
                        f"line {self.src.line(n.sourceRange.start.offset)}"
                    )
                self._reg(n.lvalue.symbol)
            return ast.VisitAction.Advance

        self.inst.visit(v)

    def _reg(self, sym: ast.Symbol) -> None:
        name = self.key(sym)
        if name in self.regs:
            return
        if "." in name:
            raise self.err(
                f"{name}: a forced reg declared in a named scope or generate block is not supported"
            )
        if sym.kind != _SY.Variable or sym.type.isUnpackedArray:
            raise self.err(f"{name}: only plain packed reg variables can be transformed")
        decl = sym.syntax.parent if sym.syntax is not None else None
        if decl is None or decl.kind != _SX.DataDeclaration:
            raise self.err(f"{name}: declared as an ANSI output reg; rewrite the port by hand")
        is_port = any(
            p.internalSymbol is not None and p.internalSymbol.name == sym.name
            for p in self.body.portList
        )
        loc = self.src.char(sym.location.offset)
        # Keep the packed range exactly as declared ([4:1], [0:3], signed), so every existing
        # X[i] / X[a:b] read indexes the new net the same way (review #5).
        t = self.span(decl.type)
        typ = self.text[t.start : t.end]
        m = re.match(r"^\s*(?:reg|logic|bit)\b\s*(.*)$", typ, re.S)
        if m is not None:
            dims = m.group(1).strip()
        elif typ.strip() in _INTEGER_TYPES:  # the same 4-state vector, spelled explicitly
            dims = _INTEGER_TYPES[typ.strip()]
        else:
            raise self.err(
                f"{name}: forced variable of type `{typ.strip()}` is not reg/logic/bit/integer/time"
            )
        self.regs[name] = ForcedReg(
            name,
            dims + " " if dims else "",
            Span(loc, loc + len(sym.name)),
            self.span(decl).end,
            is_port,
        )

    # ---- pass 2: drivers, writes, forcing sites --------------------------------------------
    def walk(self) -> None:
        def v(n: _AstNode) -> ast.VisitAction:
            k = n.kind
            if k == _SY.Instance and n.hierarchicalPath != self.inst.hierarchicalPath:
                self.sub_instance(n)
                return ast.VisitAction.Skip
            if k == _SY.Subroutine:  # bodies are entered per call; record side effects
                self.side_effects(n)
                return ast.VisitAction.Skip
            if self.is_other_scope(n):
                return ast.VisitAction.Skip
            if k == _SY.PrimitiveInstance:
                self.gate(n)
                return ast.VisitAction.Skip
            if k == _SY.UninstantiatedDef:
                # Unknown module: port directions are unknown (and slang does not bind the
                # connection expressions), so every signal named in a connection may be
                # driven by it. Tracing into any of them fails loudly.
                for name in _identifiers(n.syntax):
                    sym = self.body.find(name)
                    if sym is not None and sym.kind not in _CONSTANT_SYMBOLS:
                        self.opaque.add(self.key(sym))
                return ast.VisitAction.Skip
            if k == _SY.ContinuousAssign:
                a = n.assignment
                reads = self.reads(a.right, set())
                self.select_reads(a.left, reads)
                for nv in self.lvalues(a.left):
                    self.drive(nv, reads, frozenset())
                return ast.VisitAction.Skip
            if k in (_SY.Net, _SY.Variable) and n.initializer is not None:
                self.drivers[self.key(n)].append(
                    _Driver(frozenset(self.reads(n.initializer, set())), frozenset())
                )
            if k == _SY.ProceduralBlock:
                self.block(n)
                return ast.VisitAction.Skip
            return ast.VisitAction.Advance

        self.inst.visit(v)

    def side_effects(self, sub: ast.SubroutineSymbol) -> None:
        """Module-level variables a subroutine writes (e.g. a module-level loop index used
        in a function) depend on everything the subroutine reads. A function writing a
        forced reg is refused: its writes are not redirected."""
        own = self.key(sub) + "."
        self._stack.append(self.key(sub))
        try:
            reads = frozenset(self.reads(sub.body, set()))
        finally:
            self._stack.pop()
        for name in self.written_names(sub.body):
            if name.startswith(own):
                continue
            if name in self.forced_names and sub.subroutineKind == ast.SubroutineKind.Function:
                raise self.err(f"function {sub.name} writes forced reg {name}")
            self.drivers[name].append(_Driver(reads, frozenset()))

    def drive(
        self, nv: ast.Expression, reads: set[str] | frozenset[str], clocks: frozenset[str]
    ) -> None:
        self.drivers[self.key(nv.symbol)].append(_Driver(frozenset(reads), clocks))

    def gate(self, prim: ast.PrimitiveInstanceSymbol) -> None:
        """buf/not/and/or/nand/nor/xor/xnor/bufif*/notif* and UDPs: outputs <- inputs."""
        terms = [e for e in prim.portConnections if e is not None]
        n_out = len(terms) - 1 if prim.primitiveType.name in _MULTI_OUT else 1
        reads: set[str] = set()
        for e in terms[n_out:]:
            self.reads(e, reads)
        for e in terms[:n_out]:
            for nv in self.lvalues(e):
                if self.key(nv.symbol) in self.forced_names:
                    raise self.err(f"forced reg {self.key(nv.symbol)} driven by a primitive")
                self.drive(nv, reads, frozenset())

    def sub_instance(self, inst: ast.InstanceSymbol) -> None:
        """A module from the same file: conservatively, every output depends on every input
        (over-approximation adds triggers, it never drops one)."""
        ins: set[str] = set()
        outs = []
        for conn in inst.portConnections:
            e = conn.expression
            if e is None:
                continue
            if conn.port.direction == _AD.In:
                self.reads(e, ins)
            else:
                outs.append(e)
                if conn.port.direction == _AD.InOut:
                    self.reads(e, ins)
        for e in outs:
            for nv in self.lvalues(e):
                if self.key(nv.symbol) in self.forced_names:
                    raise self.err(
                        f"forced reg {self.key(nv.symbol)} is connected to an "
                        f"output of instance {inst.name}"
                    )
                self.drive(nv, ins, frozenset())

    def block(self, pb: ast.ProceduralBlockSymbol) -> None:
        body, edges, levels = pb.body, set(), set()
        stmt, implicit = (
            body,
            pb.procedureKind
            in (ast.ProceduralBlockKind.AlwaysComb, ast.ProceduralBlockKind.AlwaysLatch),
        )
        if body.kind == _SK.Timed:
            implicit |= self.events(body.timing, edges, levels)
            stmt = body.stmt
        elif pb.procedureKind == ast.ProceduralBlockKind.Always:
            # `always begin ... @(x); end`: the body loops, so every statement in it runs
            # again after each event/wait inside it (conservative: all of them).
            implicit |= self.inner_waits(body, edges, levels)
        if implicit:  # @* / always_comb / always_latch: sensitive to everything read
            levels |= self.reads(stmt, set())
        self.stmt(stmt, frozenset(), _Ctx(frozenset(edges), frozenset(levels)))

    def inner_waits(self, body: ast.Statement, edges: set[str], levels: set[str]) -> bool:
        implicit = False

        def v(n: _AstNode) -> ast.VisitAction:
            nonlocal implicit
            if n.kind == _SK.Timed:
                implicit |= self.events(n.timing, edges, levels)
            elif n.kind == _SK.Wait:
                self.reads(n.cond, levels)
            return ast.VisitAction.Advance

        body.visit(v)
        return implicit

    def events(self, timing: ast.TimingControl, edges: set[str], levels: set[str]) -> bool:
        k = timing.kind
        if k == _TK.EventList:
            return any([self.events(e, edges, levels) for e in timing.events])
        if k == _TK.SignalEvent:
            self.reads(timing.expr, edges if timing.edge in _EDGES else levels)
            if timing.iffCondition is not None:
                self.reads(timing.iffCondition, levels)
            return False
        if k == _TK.ImplicitEvent:
            return True
        if k in _DELAYS:
            return False
        raise self.err(f"unsupported timing control {k.name}")

    def seq(self, stmts: list[ast.Statement], conds: frozenset[str], ctx: _Ctx) -> None:
        pending: set[str] = set()
        for s in stmts:
            if s.kind == _SK.Timed and s.timing.kind in _DELAYS:
                pending.clear()
            hit = pending & self.rvalue_names(s)
            if hit:
                raise self.err(
                    f"{sorted(hit)[0]} is read after its procedural assign/deassign "
                    "in the same block without an intervening delay"
                )
            self.stmt(s, conds, ctx)
            pending |= self.forced_in(s)

    def stmt(self, s: ast.Statement, conds: frozenset[str], ctx: _Ctx) -> None:
        k = s.kind
        if k == _SK.Block:
            self.stmt(s.body, conds, ctx)
        elif k == _SK.List:
            self.seq(list(s.list), conds, ctx)
        elif k == _SK.Conditional:
            c = set(conds)
            for cond in s.conditions:
                self.reads(cond.expr, c)
            self.stmt(s.ifTrue, frozenset(c), ctx)
            if s.ifFalse is not None:
                self.stmt(s.ifFalse, frozenset(c), ctx)
        elif k == _SK.Case:
            c = set(conds)
            self.reads(s.expr, c)
            for item in s.items:
                for e in item.expressions:
                    self.reads(e, c)
            for item in s.items:
                self.stmt(item.stmt, frozenset(c), ctx)
            if s.defaultCase is not None:
                self.stmt(s.defaultCase, frozenset(c), ctx)
        elif k == _SK.Timed:
            edges, levels = set(ctx.edges), set(ctx.levels)
            self.events(s.timing, edges, levels)
            self.stmt(s.stmt, conds, _Ctx(frozenset(edges), frozenset(levels)))
        elif k == _SK.Wait:
            levels = set(ctx.levels)
            self.reads(s.cond, levels)
            self.stmt(s.stmt, conds, _Ctx(ctx.edges, frozenset(levels)))
        elif k == _SK.ExpressionStatement:
            self.expr_stmt(s.expr, conds, ctx)
        elif k == _SK.ProceduralAssign:
            self.force(s, conds, ctx)
        elif k == _SK.ProceduralDeassign:
            name = self.key(s.lvalue.symbol)
            self.regs[name].deassigns.append(self.span(s))
            self._site(name, ctx)
        elif k in _LOOPS:
            loop_conds = frozenset(self.reads(s, set(conds)))
            if (self.written_names(s) - self.written_names(s.body)) & self.forced_names:
                raise self.err("a loop header writes a forced reg")
            self._generic_writes(s, loop_conds, ctx)  # loop variables
            self.stmt(s.body, loop_conds, ctx)
        elif k in _NOOPS:
            pass
        elif k == _SK.VariableDeclaration:  # a block-local `integer i = e;`
            init = s.symbol.initializer
            reads = set(conds) | set(ctx.levels)
            if init is not None:
                self.reads(init, reads)
            self.drivers[self.key(s.symbol)].append(
                _Driver(frozenset(reads), frozenset(ctx.edges - reads))
            )
        elif k == _SK.EventTrigger:  # `-> ev;`: ev fires under this block's conditions
            reads = set(conds) | set(ctx.levels)
            for nv in self.lvalues(s.target):
                self.drive(nv, reads, frozenset(ctx.edges - reads))
        else:
            if self.forced_in(s) or self.written_names(s) & self.forced_names:
                raise self.err(f"unhandled statement kind {k.name} touches a forced reg")
            self._generic_writes(s, frozenset(self.reads(s, set(conds))), ctx)

    def expr_stmt(self, e: ast.Expression, conds: frozenset[str], ctx: _Ctx) -> None:
        if e.kind == _EK.Assignment:
            reads = set(conds) | set(ctx.levels)
            self.reads(e.right, reads)
            self.select_reads(e.left, reads)
            for nv in self.lvalues(e.left):
                name = self.key(nv.symbol)
                self.drive(nv, reads, frozenset(ctx.edges - reads))
                if name in self.regs:
                    self.regs[name].writes.add(self.span(nv))
        elif e.kind == _EK.Call and not e.isSystemCall:
            sub = e.subroutine
            path = self.key(sub)
            if path in self._stack:
                raise self.err(f"recursive call of {sub.name}")
            args = set(conds)
            for formal, actual in zip(sub.arguments, e.arguments, strict=False):
                if actual.kind == _EK.Assignment:  # output/inout argument: actual = formal
                    for nv in self.lvalues(actual.left):
                        if self.key(nv.symbol) in self.regs:
                            raise self.err(f"forced reg passed to an output argument of {sub.name}")
                        self.drive(
                            nv,
                            {self.key(formal)} | set(conds) | set(ctx.levels),
                            frozenset(ctx.edges),
                        )
                if formal.direction in (_AD.In, _AD.InOut):
                    val = actual.right if actual.kind == _EK.Assignment else actual
                    self.drivers[self.key(formal)].append(
                        _Driver(
                            frozenset(self.reads(val, set(conds) | set(ctx.levels))),
                            frozenset(ctx.edges),
                        )
                    )
                self.reads(actual, args)
            self._stack.append(path)
            try:
                self.stmt(sub.body, frozenset(args), ctx)
            finally:
                self._stack.pop()
        elif self.written_names_expr(e) & self.forced_names:
            raise self.err(f"unhandled expression statement {e.kind.name} writes a forced reg")

    def written_names_expr(self, e: ast.Expression) -> set[str]:
        out: set[str] = set()

        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind == _EK.Assignment:
                out.update(self.key(x.symbol) for x in self.lvalues(n.left))
            elif n.kind == _EK.UnaryOp and n.op.name in (
                "Preincrement",
                "Predecrement",
                "Postincrement",
                "Postdecrement",
            ):
                out.update(self.key(x.symbol) for x in self.lvalues(n.operand))
            return ast.VisitAction.Advance

        e.visit(v)
        return out

    def force(self, s: ast.Statement, conds: frozenset[str], ctx: _Ctx) -> None:
        a = s.assignment
        name = self.key(a.left.symbol)
        rhs = self.reads(a.right, set())
        if name in rhs:
            raise self.err(f"override expression of {name} reads {name}")
        for r in sorted(rhs):
            if "." in r and not r.startswith("glbl."):
                raise self.err(f"override expression of {name} reads local {r}")
        self.regs[name].overrides.append((self.span(s), self.span(a.right)))
        self.drivers[name].append(
            _Driver(frozenset(rhs | conds | ctx.levels), frozenset(ctx.edges - rhs - conds))
        )
        self._site(name, ctx)

    def _site(self, name: str, ctx: _Ctx) -> None:
        self.regs[name].sensitivity |= ctx.edges | ctx.levels

    def _generic_writes(self, s: ast.Statement, reads: frozenset[str], ctx: _Ctx) -> None:
        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind == _EK.Assignment:
                for nv in self.lvalues(n.left):
                    self.drive(nv, reads, frozenset(ctx.edges - reads))
            return ast.VisitAction.Advance

        s.visit(v)

    # ---- cone tracing ------------------------------------------------------------------------
    def trace(self, start: set[str]) -> tuple[set[str], set[str]]:
        trig: set[str] = set()
        en: set[str] = set()
        seen: set[tuple[str, bool]] = set()
        work = [(s, False) for s in sorted(start)]
        while work:
            s, via_clock = work.pop()
            if (s, via_clock) in seen:
                continue
            seen.add((s, via_clock))
            if s.startswith("glbl.") or s in self.inputs:
                (en if via_clock else trig).add(s)
                continue
            if s in self.opaque:
                raise self.err(
                    f"cannot trace {s}: it is driven by an instance output "
                    "of a module that is not in the model's file"
                )
            if not self.drivers.get(s):
                raise self.err(
                    f"cannot resolve the driver of {s} while tracing triggers "
                    "(spec §6.2: never drop a signal silently)"
                )
            for d in self.drivers[s]:
                work += [(r, via_clock) for r in d.reads]
                work += [(c, True) for c in d.clocks]
        return trig, en - trig


def _compile(
    path: Path, module: str, glbl: Path, overrides: dict[str, str]
) -> tuple[ast.Compilation, ast.InstanceSymbol]:
    opts = ast.CompilationOptions()
    opts.paramOverrides = [f"{k}={v}" for k, v in overrides.items()]
    comp = ast.Compilation(pyslang.Bag([opts]))
    comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(path)))
    comp.addSyntaxTree(pyslang.syntax.SyntaxTree.fromFile(str(glbl)))
    all_diags = comp.getAllDiagnostics()
    if any(d.code == pyslang.Diags.BadProceduralAssign for d in all_diags):
        raise TransformError(
            module, "procedural assign/deassign to a select or concatenation (or a net)"
        )
    diags = [d for d in all_diags if d.isError() and not _is_benign(d)]
    if diags:
        report = pyslang.DiagnosticEngine.reportAll(comp.sourceManager, diags)
        raise TransformError(module, f"pyslang errors with {overrides or 'defaults'}:\n{report}")
    inst = next((i for i in comp.getRoot().topInstances if i.name == module), None)
    if inst is None:
        raise TransformError(module, f"module not found as a top-level module in {path}")
    return comp, inst


def _check_coverage(
    path: Path, module: str, src: _Source, forced: dict[str, ForcedReg], elaborated: set[int]
) -> None:
    """Backstops: every procedural assign/deassign in the file was analysed, and no
    generate branch that never elaborated mentions a forced reg."""
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    seen = {o[0].start for x in forced.values() for o in x.overrides}
    seen |= {d.start for x in forced.values() for d in x.deassigns}
    buffer = _module_decl(tree, module).header.name.location.buffer
    for n in _walk_syntax(tree.root):
        if n.kind not in _SYNTAX_FORCE:
            continue
        r = n.sourceRange
        if r.start.buffer != buffer:
            raise TransformError(
                module,
                "a procedural assign/deassign is inside a macro "
                "expansion or include; the transform only rewrites the "
                "model's own text",
            )
        if src.char(r.start.offset) in seen:
            continue
        line = src.line(r.start.offset)
        owner = n.parent
        while owner is not None and owner.kind != _SX.ModuleDeclaration:
            owner = owner.parent
        other = owner.header.name.valueText if owner is not None else None
        if other != module:
            raise TransformError(
                module,
                f"procedural assign/deassign at line {line} is in "
                f"module {other}, not {module}; only the analysed module is "
                "transformed",
            )
        raise TransformError(
            module,
            f"procedural assign/deassign at line {line} was never "
            "elaborated (an untaken generate branch or an uncalled task)",
        )
    constructs, _ = _generate_constructs(tree, module)
    for c in constructs:
        for arm in c.arms:
            if arm.sourceRange.start.offset in elaborated:
                continue
            hit = _identifiers(arm) & set(forced)
            if hit:
                line = src.line(arm.sourceRange.start.offset)
                raise TransformError(
                    module,
                    f"generate branch at line {line} mentions forced "
                    f"reg {sorted(hit)[0]} but no generate configuration "
                    "elaborates it",
                )


def analyze(
    path: Path, module: str, glbl: Path, choices: dict[str, list[str]] | None = None
) -> Analysis:
    """Analyse ``module`` in ``path`` under every generate configuration (the union)."""
    src = _Source(Path(path))
    merged: dict[str, ForcedReg] = {}
    elaborated: set[int] = set()
    end = -1
    for overrides in generate_configs(path, module, choices):
        _, inst = _compile(path, module, glbl, overrides)
        w = _Walker(module, inst, src)
        w.prescan()
        w.walk()
        elaborated |= w.generate_blocks
        for x in w.regs.values():
            if not x.overrides:
                raise TransformError(module, f"{x.name} is deassigned but never assigned")
            trig, en = w.trace(x.sensitivity)
            if not trig:
                raise TransformError(
                    module,
                    f"{x.name}: no trigger found (the forcing block has "
                    "no sensitivity list or its cone has no primitive input)",
                )
            m = merged.setdefault(
                x.name, ForcedReg(x.name, x.dims, x.decl_name, x.decl_end, x.is_port)
            )
            m.overrides = sorted(set(m.overrides) | set(x.overrides), key=lambda o: o[0].start)
            m.deassigns = sorted(set(m.deassigns) | set(x.deassigns), key=lambda d: d.start)
            m.writes |= x.writes
            m.sensitivity |= x.sensitivity
            m.triggers |= trig
            m.enablers |= en
        end = src.char(inst.body.definition.syntax.endmodule.location.offset)
    _check_coverage(Path(path), module, src, merged, elaborated)
    return Analysis(module, Path(path), src.text, end, merged)
