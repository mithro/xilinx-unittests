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
from collections.abc import Callable, Iterable, Iterator
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
_REAL_TYPES = ("real", "realtime")
# System functions that only read their arguments (for the never-written-variable check).
_READ_ONLY_SYSTEM = frozenset(
    {
        "$display",
        "$write",
        "$strobe",
        "$monitor",
        "$info",
        "$warning",
        "$error",
        "$fatal",
        "$finish",
        "$stop",
        "$time",
        "$stime",
        "$realtime",
        "$rtoi",
        "$itor",
        "$realtobits",
        "$bitstoreal",
        "$signed",
        "$unsigned",
        "$abs",
        "$clog2",
        "$ceil",
        "$floor",
        "$pow",
        "$sqrt",
        "$ln",
        "$log10",
        "$exp",
        "$bits",
        "$isunknown",
        "$countones",
        "$onehot",
    }
)
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


@dataclass(frozen=True)
class StaleRead:
    """A procedural read of forced reg X after an assign/deassign of X in the same block, with
    no delay or event control between them (ruling S18). The rewrite substitutes the active
    value for it: ``active`` is the statement span of the active ``assign X = e_k;``, or
    ``None`` after a ``deassign X;`` (X__base then holds the value), or ``FRESH`` after an
    ordinary blocking write of X on some path (X__base changed, the net X has not
    propagated yet: the rewrite reads X's current value from X__base / the active override
    at the read itself, which is right whatever the override state)."""

    span: Span
    active: Span | None


# Sentinel for an override state that differs between the paths reaching a read.
_AMBIGUOUS = Span(-1, -1)
#: StaleRead.active for a read after an ordinary blocking write (see StaleRead).
FRESH = Span(-2, -2)


@dataclass
class ForcedReg:
    name: str
    dims: str  # declaration text between the type keyword and the name, e.g. "signed [4:1] "
    type: str  # declared type keyword: reg | logic | bit | integer | time | real | realtime
    decl_name: Span
    decl_end: int
    is_port: bool
    # Set for a non-ANSI `output reg X;`: the span of the `reg`/`logic` keyword, which the
    # rewrite deletes (X becomes the port net). decl_name is then NOT renamed: the rewrite
    # declares `reg <dims>X__base;` next to the port declaration instead.
    reg_keyword: Span | None = None
    overrides: list[tuple[Span, Span]] = field(default_factory=list)  # (statement, rhs)
    deassigns: list[Span] = field(default_factory=list)
    writes: set[Span] = field(default_factory=set)
    sensitivity: set[str] = field(default_factory=set)
    triggers: set[str] = field(default_factory=set)
    enablers: set[str] = field(default_factory=set)
    stale_reads: set[StaleRead] = field(default_factory=set)


@dataclass
class Analysis:
    """One module's forced regs. For the analysed model, ``submodules`` holds the same-file
    helper modules it instantiates that force regs too (each rewritten in place); their
    triggers and enablers are already traced to the model's own ports and glbl."""

    model: str
    path: Path
    text: str
    endmodule: int
    forced: dict[str, ForcedReg]
    submodules: dict[str, Analysis] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # `deassign X;` of a reg that is never procedurally assigned: a no-op in Verilog, so the
    # rewrite replaces each with a null statement `;` (FF18_INTERNAL_VLOG ALMOSTFULL).
    noop_deassigns: list[Span] = field(default_factory=list)

    def _regs(self) -> list[ForcedReg]:
        return [*self.forced.values(), *(x for a in self.submodules.values() for x in a._regs())]

    @property
    def triggers(self) -> list[str]:
        return sorted(set().union(*(f.triggers for f in self._regs())))

    @property
    def enablers(self) -> list[str]:
        en = set().union(*(f.enablers for f in self._regs()))
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


def _module_names(tree: SyntaxTree) -> list[str]:
    return [
        n.header.name.valueText for n in _walk_syntax(tree.root) if n.kind == _SX.ModuleDeclaration
    ]


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


def _all_arms(tree: SyntaxTree, module: str) -> list[SyntaxNode]:
    """Every generate if/case arm of ``module``, at any nesting depth."""
    arms: list[SyntaxNode] = []
    for n in _walk_syntax(_module_decl(tree, module)):
        if n.kind == _SX.IfGenerate:
            arms.append(n.block)
            ec = n.elseClause
            if ec is not None and ec.clause.kind != _SX.IfGenerate:
                arms.append(ec.clause)
        elif n.kind == _SX.CaseGenerate:
            arms += [item.clause for item in n.items]
    return arms


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
    constructs, nested = _generate_constructs(tree, module_name)
    if nested:
        raise TransformError(
            module_name, f"nested generate conditions are not supported: `{nested[0]}`"
        )
    work = [(c, _localparams(tree, module_name), True) for c in constructs]
    # Same-file helper modules (ruling S18): their generate conditions usually name a
    # parameter the model passes down under the same name (FF18_INTERNAL_VLOG SIM_DEVICE).
    # Enumerate the model's parameter of that name; a helper branch this cannot reach is
    # caught by analyze()'s coverage check if it matters.
    for other in _module_names(tree):
        if other != module_name:
            helper, _ = _generate_constructs(tree, other)
            work += [(c, _localparams(tree, other), False) for c in helper]
    out: list[dict[str, str]] = [{}]
    for c, local, own in work:
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
        if empty and own:
            raise TransformError(
                module_name,
                f"cannot enumerate generate configurations: no "
                f"candidate values for {empty} in `{_plain(c.conds[0])}`",
            )
        names = [n for n in names if cands[n]]
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
    def __init__(
        self, model: str, inst: ast.InstanceSymbol, src: _Source, parent: _Walker | None = None
    ) -> None:
        self.model, self.inst, self.body, self.src = model, inst, inst.body, src
        self.parent = parent
        self.defname = inst.body.definition.name
        self.children: list[_Walker] = []
        # instance path -> input port name -> signals (in this module) its connection reads
        self.port_inputs: dict[str, dict[str, set[str]]] = {}
        self.variables: set[str] = set()  # module-level variables (never-written check)
        self.notes: list[str] = []
        self.always_forced: set[str] = set()  # forced from an always block (not only initial)
        self._stale: dict[str, dict[Span, Span | None]] = defaultdict(dict)
        self._proc = ast.ProceduralBlockKind.Always
        self._dry = False  # loop fixpoint pre-pass: compute states without recording
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
        where = f"in {self.defname} ({self.inst.hierarchicalPath}): " if self.parent else ""
        return TransformError(self.model, where + msg)

    def all(self) -> Iterator[_Walker]:
        yield self
        for c in self.children:
            yield from c.all()

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
            if e.symbol.hierarchicalPath.startswith("glbl."):
                return []  # into the simulator's glbl (PLL_LOCKG): outside the model
            raise self.err(
                f"hierarchical write to {e.symbol.hierarchicalPath} at line "
                f"{self.src.line(e.sourceRange.start.offset)} is not supported (its driver "
                "would be invisible to the trigger trace)"
            )
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
                if n.assignment.left.kind == _EK.HierarchicalValue:
                    raise self.err(
                        f"procedural assign to a hierarchical reference at line "
                        f"{self.src.line(n.sourceRange.start.offset)}"
                    )
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
        reg_keyword = None
        if decl is not None and decl.kind == _SX.PortDeclaration:
            # non-ANSI `output reg X;` (FF18_INTERNAL_VLOG): the rewrite deletes the `reg`
            # keyword, so X becomes the port net, and declares X__base itself
            dtype = decl.header.dataType if decl.header.kind == _SX.VariablePortHeader else None
            if (
                dtype is None
                or dtype.kind not in (_SX.RegType, _SX.LogicType)
                or len(_nodes(decl.declarators)) != 1
            ):
                raise self.err(
                    f"{name}: port declaration `{_plain(decl)}` cannot be split into a net "
                    "port and a shadow reg (one `output reg`/`output logic` name per line)"
                )
            kw = dtype.keyword
            if kw.location.buffer != self.buffer:
                raise self.err(f"{name}: port declaration is inside a macro expansion")
            start = self.src.char(kw.location.offset)
            reg_keyword = Span(start, start + len(kw.rawText))
            type_node = dtype
        elif decl is None or decl.kind != _SX.DataDeclaration:
            raise self.err(f"{name}: declared as an ANSI output reg; rewrite the port by hand")
        else:
            type_node = decl.type
        is_port = any(
            p.internalSymbol is not None and p.internalSymbol.name == sym.name
            for p in self.body.portList
        )
        loc = self.src.char(sym.location.offset)
        # Keep the packed range exactly as declared ([4:1], [0:3], signed), so every existing
        # X[i] / X[a:b] read indexes the new net the same way (review #5).
        t = self.span(type_node)
        typ = self.text[t.start : t.end].strip()
        m = re.match(r"^(reg|logic|bit)\b\s*(.*)$", typ, re.S)
        if m is not None:
            kind, dims = m.group(1), m.group(2).strip()
        elif typ in _INTEGER_TYPES:  # the same 4-state vector, spelled explicitly
            kind, dims = typ, _INTEGER_TYPES[typ]
        elif typ in _REAL_TYPES:  # ruling S18: X__base/X__ovr_k are declared real too
            kind, dims = typ, ""
        else:
            raise self.err(
                f"{name}: forced variable of type `{typ}` is not "
                "reg/logic/bit/integer/time/real/realtime"
            )
        self.regs[name] = ForcedReg(
            name,
            dims + " " if dims else "",
            kind,
            Span(loc, loc + len(sym.name)),
            self.span(decl).end,
            is_port,
            reg_keyword,
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
            if k == _SY.Variable:
                self.variables.add(self.key(n))
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
        terms = list(prim.portConnections)
        n_out = len(terms) - 1 if prim.primitiveType.name in _MULTI_OUT else 1
        outs = [e for e in terms[:n_out] if e is not None]
        reads: set[str] = set()
        for e in terms[n_out:]:
            if e is not None:
                self.reads(e, reads)
        for e in outs:
            for nv in self.lvalues(e):
                if self.key(nv.symbol) in self.forced_names:
                    raise self.err(f"forced reg {self.key(nv.symbol)} driven by a primitive")
                self.drive(nv, reads, frozenset())

    def sub_instance(self, inst: ast.InstanceSymbol) -> None:
        """A module from the same file: conservatively, every output depends on every input
        (over-approximation adds triggers, it never drops one)."""
        ins: set[str] = set()
        outs = []
        ports = self.port_inputs.setdefault(inst.hierarchicalPath, {})
        for conn in inst.portConnections:
            e = conn.expression
            if e is None:
                continue
            if conn.port.direction in (_AD.In, _AD.InOut):
                ports[conn.port.name] = self.reads(e, set())
                ins |= ports[conn.port.name]
            if conn.port.direction != _AD.In:
                outs.append(e)
        for e in outs:
            for nv in self.lvalues(e):
                if self.key(nv.symbol) in self.forced_names:
                    raise self.err(
                        f"forced reg {self.key(nv.symbol)} is connected to an "
                        f"output of instance {inst.name}"
                    )
                self.drive(nv, ins, frozenset())
        # A same-file helper module may force regs itself (ruling S18): analyse its body too.
        child = _Walker(self.model, inst, self.src, parent=self)
        child.prescan()
        child.walk()
        self.children.append(child)

    def lift(self, trig: set[str], en: set[str]) -> tuple[set[str], set[str]]:
        """Map roots that are this module's input ports up through the instance
        connections to the analysed model's own ports (and glbl)."""
        w = self
        while w.parent is not None:
            p = w.parent
            conns = p.port_inputs.get(w.inst.hierarchicalPath, {})
            nt: set[str] = set()
            ne: set[str] = set()
            for t in trig:
                tr, e = ({t}, set()) if t.startswith("glbl.") else p.trace(conns.get(t, set()))
                nt |= tr
                ne |= e
            for x in en:
                tr, e = ({x}, set()) if x.startswith("glbl.") else p.trace(conns.get(x, set()))
                ne |= tr | e
            trig, en, w = nt, ne - nt, p
        return trig, en

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
        self._proc = pb.procedureKind
        self.stmt(stmt, frozenset(), _Ctx(frozenset(edges), frozenset(levels)))
        start: dict[str, Span | None] = {}
        if pb.procedureKind == ast.ProceduralBlockKind.Always and body.kind != _SK.Timed:
            # the body loops back to its start without suspending: a read at the top sees
            # the state left by the previous iteration (and none on the first)
            dry, self._dry = self._dry, True
            try:
                while True:
                    nxt = _merge({}, self.track(stmt, start))
                    if nxt == start:
                        break
                    start = nxt
            finally:
                self._dry = dry
        self.track(stmt, start)

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
        for s in stmts:
            self.stmt(s, conds, ctx)
            ctx = self.after_wait(s, ctx)

    def after_wait(self, s: ast.Statement, ctx: _Ctx) -> _Ctx:
        """Statements that follow a wait in a sequence run when it ends: `@(x);`, `wait(c);`
        and a polling loop (`while (c) #d;`, SRL16E's initialisation) add their signals."""
        edges, levels = set(ctx.edges), set(ctx.levels)
        if s.kind == _SK.Timed and s.timing.kind not in _DELAYS:
            if self.events(s.timing, edges, levels):
                levels |= self.reads(s.stmt, set())
        elif s.kind == _SK.Wait:
            self.reads(s.cond, levels)
        elif s.kind in _LOOPS and self.has_timing(s.body):
            for part in self.loop_header(s):
                self.reads(part, levels)
        else:
            return ctx
        return _Ctx(frozenset(edges), frozenset(levels))

    def has_timing(self, s: ast.Statement) -> bool:
        found = False

        def v(n: _AstNode) -> ast.VisitAction:
            nonlocal found
            found |= n.kind in (_SK.Timed, _SK.Wait)
            return ast.VisitAction.Advance

        s.visit(v)
        return found

    def loop_header(self, s: ast.Statement) -> list[_AstNode]:
        k = s.kind
        if k == _SK.ForLoop:
            return [*s.initializers, *([s.stopExpr] if s.stopExpr is not None else []), *s.steps]
        if k in (_SK.WhileLoop, _SK.DoWhileLoop):
            return [s.cond]
        if k == _SK.RepeatLoop:
            return [s.count]
        if k == _SK.ForeachLoop:
            return [s.arrayRef]
        return []

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
        if self._proc != ast.ProceduralBlockKind.Initial:
            self.always_forced.add(name)

    # ---- reads of a forced reg right after its assign/deassign (ruling S18) --------------
    def track(
        self, s: ast.Statement, st: dict[str, Span | None], in_task: str | None = None
    ) -> dict[str, Span | None]:
        """Walk a block in execution order with the override state of each forced reg
        assigned/deassigned since the last delay or event control; record (or refuse) every
        read of such a reg. Returns the state after ``s``."""
        k = s.kind
        if k == _SK.Block:
            if s.blockKind != ast.StatementBlockKind.Sequential and (st or self.forced_in(s)):
                line = self.src.line(s.sourceRange.start.offset)
                raise self.err(
                    f"fork/join (parallel block) at line {line} next to a procedural "
                    "assign/deassign: execution order is not static"
                )
            return self.track(s.body, st, in_task)
        if k == _SK.List:
            for x in s.list:
                st = self.track(x, st, in_task)
            return st
        if k == _SK.Timed:
            self.stale(s.timing, st, in_task, "an event control")
            return self.track(s.stmt, {}, in_task)  # suspended: every net has propagated
        if k == _SK.Wait:
            self.stale(s.cond, st, in_task, "a wait condition")
            # may or may not suspend: another process may change the override meanwhile
            return self.track(s.stmt, {n: _AMBIGUOUS for n in st}, in_task)
        if k == _SK.ProceduralAssign:
            self.stale(s.assignment.right, st, in_task, "an override expression")
            return {**st, self.key(s.assignment.left.symbol): self.span(s)}
        if k == _SK.ProceduralDeassign:
            # the rewrite captures the active override value itself: not a read of X
            return {**st, self.key(s.lvalue.symbol): None}
        if k == _SK.Conditional:
            for c in s.conditions:
                self.stale(c.expr, st, in_task)
            a = self.track(s.ifTrue, st, in_task)
            b = self.track(s.ifFalse, st, in_task) if s.ifFalse is not None else st
            return _merge(a, b)
        if k == _SK.Case:
            self.stale(s.expr, st, in_task)
            for item in s.items:
                for e in item.expressions:
                    self.stale(e, st, in_task)
            outs = [self.track(item.stmt, st, in_task) for item in s.items]
            outs.append(self.track(s.defaultCase, st, in_task) if s.defaultCase else st)
            return _merge(*outs)
        if k == _SK.ExpressionStatement:
            return self.track_expr(s.expr, st, in_task)
        if k in _LOOPS:
            dry, self._dry = self._dry, True
            try:  # fixpoint: the body may run any number of times, including zero
                cur = st
                while True:
                    nxt = _merge(st, self.track(s.body, cur, in_task))
                    if nxt == cur:
                        break
                    cur = nxt
            finally:
                self._dry = dry
            for part in self.loop_header(s):
                self.stale(part, cur, in_task)
            self.track(s.body, cur, in_task)
            return cur
        if k == _SK.VariableDeclaration:
            if s.symbol.initializer is not None:
                self.stale(s.symbol.initializer, st, in_task)
            return st
        if k in _NOOPS:
            return st
        self.stale(s, st, in_task)
        return st

    def track_expr(
        self, e: ast.Expression, st: dict[str, Span | None], in_task: str | None
    ) -> dict[str, Span | None]:
        if e.kind == _EK.Assignment:
            self.stale(e.right, st, in_task)
            self._select_nodes(e.left, lambda n: self.stale(n, st, in_task))
            if not e.isNonBlocking and e.timingControl is not None:
                return {}  # `x = #d y;` suspends the process
            if not e.isNonBlocking:
                # An ordinary blocking write changes X__base now; the net X follows later.
                # Under an assign/deassign of this block the state already names X's value
                # (the override; X__base), otherwise X must be read fresh.
                hit = {self.key(x.symbol) for x in self.lvalues(e.left)} & set(self.regs)
                upd = {n: FRESH for n in hit if st.get(n, _AMBIGUOUS) in (_AMBIGUOUS, FRESH)}
                if upd:
                    return {**st, **upd}
            return st
        if e.kind == _EK.Call and not e.isSystemCall:
            for a in e.arguments:
                self.stale(a.right if a.kind == _EK.Assignment else a, st, in_task)
            return self.track(e.subroutine.body, st, e.subroutine.name)
        self.stale(e, st, in_task)
        return st

    def _select_nodes(self, e: ast.Expression, fn: Callable[[ast.Expression], None]) -> None:
        k = e.kind
        if k == _EK.ElementSelect:
            fn(e.selector)
            self._select_nodes(e.value, fn)
        elif k == _EK.RangeSelect:
            fn(e.left)
            fn(e.right)
            self._select_nodes(e.value, fn)
        elif k == _EK.Concatenation:
            for op in e.operands:
                self._select_nodes(op, fn)

    def stale(
        self,
        node: _AstNode,
        st: dict[str, Span | None],
        in_task: str | None,
        where: str | None = None,
    ) -> None:
        if not st:
            return

        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind in (_EK.NamedValue, _EK.HierarchicalValue):
                name = self.key(n.symbol)
                if name in st:
                    self.stale_read(name, n, st[name], in_task, where)
            elif n.kind == _EK.Call and not n.isSystemCall:
                hit = self.reads(n.subroutine.body, set()) & set(st)
                if hit:
                    raise self.err(
                        f"{sorted(hit)[0]} is read inside function {n.subroutine.name} right "
                        "after its procedural assign/deassign; the read cannot be substituted"
                    )
            return ast.VisitAction.Advance

        node.visit(v)

    def stale_read(
        self,
        name: str,
        n: ast.Expression,
        active: Span | None,
        in_task: str | None,
        where: str | None,
    ) -> None:
        line = self.src.line(n.sourceRange.start.offset)
        after = "a blocking write" if active == FRESH else "its procedural assign/deassign"
        if where is not None:
            raise self.err(
                f"{name} is read in {where} at line {line} right after {after}; the read "
                "cannot be substituted"
            )
        if in_task is not None:
            raise self.err(
                f"{name} is read in task {in_task} at line {line} right after {after} in "
                "the caller; the read cannot be substituted"
            )
        if active == _AMBIGUOUS:
            raise self.err(
                f"cannot determine statically which override of {name} is active at the read "
                f"at line {line} (paths from different assign/deassign/delays meet)"
            )
        if self._dry:
            return
        span = self.span(n)
        seen = self._stale[name]
        was = seen.get(span, active)
        if FRESH in (was, active):
            active = FRESH  # a fresh read is right in every state
        elif was != active:
            raise self.err(f"the read of {name} at line {line} sees different overrides")
        seen[span] = active

    def _generic_writes(self, s: ast.Statement, reads: frozenset[str], ctx: _Ctx) -> None:
        def v(n: _AstNode) -> ast.VisitAction:
            if n.kind == _EK.Assignment:
                for nv in self.lvalues(n.left):
                    self.drive(nv, reads, frozenset(ctx.edges - reads))
            return ast.VisitAction.Advance

        s.visit(v)

    def never_written(self, name: str) -> bool:
        """Syntax-level proof that module-level variable ``name`` is never a write target:
        not an assignment lvalue, not incremented, not passed to a task/function or port,
        not procedurally assigned. Its value is then its type default, a constant."""
        decl = self.body.definition.syntax
        root = decl
        while root.parent is not None:
            root = root.parent
        for n in _walk_syntax(root):  # `M.name` anywhere in the file may write it
            if n.kind == _SX.ScopedName and _plain(n).split(".")[-1].strip() == name:
                return False
        for n in _walk_syntax(decl):
            if n.kind != _SX.IdentifierName or n.identifier.valueText != name:
                continue
            off = n.sourceRange.start.offset
            a = n.parent
            while a is not None and a is not decl:
                kn = a.kind.name
                if kn.endswith("AssignmentExpression"):
                    r = a.left.sourceRange
                    if r.start.offset <= off < r.end.offset:
                        return False
                elif "crement" in kn or "PortConnection" in kn or kn.startswith("Procedural"):
                    return False
                elif kn == "InvocationExpression":
                    callee = _plain(a.left)
                    if callee not in _READ_ONLY_SYSTEM:
                        return False
                a = a.parent
        return True

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
            if not self.drivers.get(s) and s in self.variables and self.never_written(s):
                note = f"{self.defname}.{s}: never written; treated as constant"
                if note not in self.notes:
                    self.notes.append(note)
                continue
            if not self.drivers.get(s):
                raise self.err(
                    f"cannot resolve the driver of {s} while tracing triggers "
                    "(spec §6.2: never drop a signal silently)"
                )
            for d in self.drivers[s]:
                work += [(r, via_clock) for r in d.reads]
                work += [(c, True) for c in d.clocks]
        return trig, en - trig


def _merge(*states: dict[str, Span | None]) -> dict[str, Span | None]:
    """The state where paths meet: a reg keeps its override only if every path agrees. A
    FRESH read is right on every path, so FRESH on any path wins."""
    names = set().union(*states)
    missing = object()
    out: dict[str, Span | None] = {}
    for n in names:
        vals = {st.get(n, missing) for st in states}
        if FRESH in vals:
            out[n] = FRESH
        else:
            out[n] = next(iter(vals)) if len(vals) == 1 else _AMBIGUOUS
    return out


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
    path: Path,
    module: str,
    src: _Source,
    forced: dict[str, dict[str, ForcedReg]],
    elaborated: set[int],
    instantiated: set[str],
) -> None:
    """Backstops: every procedural assign/deassign in the file was analysed (in the model or
    a helper module it instantiates), and no generate branch that never elaborated mentions
    a forced reg of its module."""
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    regs = [x for m in forced.values() for x in m.values()]
    seen = {o[0].start for x in regs for o in x.overrides} | {
        d.start for x in regs for d in x.deassigns
    }
    buffer = _module_decl(tree, module).header.name.location.buffer
    for n in _walk_syntax(tree.root):
        if n.kind not in _SYNTAX_FORCE:
            continue
        r = n.sourceRange
        if r.start.buffer != buffer:
            raise TransformError(
                module,
                "a procedural assign/deassign is inside a macro expansion or include; the "
                "transform only rewrites the model's own text",
            )
        if src.char(r.start.offset) in seen:
            continue
        line = src.line(r.start.offset)
        owner = n.parent
        while owner is not None and owner.kind != _SX.ModuleDeclaration:
            owner = owner.parent
        other = owner.header.name.valueText if owner is not None else None
        if other != module and other not in forced:
            raise TransformError(
                module,
                f"procedural assign/deassign at line {line} is in module {other}, which "
                f"{module} does not instantiate; only instantiated modules are transformed",
            )
        raise TransformError(
            module,
            f"procedural assign/deassign at line {line} (module {other}) was never "
            "elaborated (an untaken generate branch or an uncalled task)",
        )
    # Every generate branch of the model and of every same-file module it instantiates must
    # be elaborated by some configuration: an unelaborated branch may hold a write, a forcing
    # statement or a driver in a trigger cone (review fix round 1).
    for name in sorted(instantiated):
        for arm in _all_arms(tree, name):
            if arm.sourceRange.start.offset not in elaborated:
                raise TransformError(
                    module,
                    f"generate branch at line {src.line(arm.sourceRange.start.offset)} (module "
                    f"{name}): no generate configuration elaborates it",
                )


def _copy(x: ForcedReg) -> ForcedReg:
    """An empty ForcedReg with ``x``'s declaration facts, to merge configurations into."""
    return ForcedReg(x.name, x.dims, x.type, x.decl_name, x.decl_end, x.is_port, x.reg_keyword)


def _merge_reg(m: ForcedReg, x: ForcedReg, model: str) -> None:
    m.overrides = sorted(set(m.overrides) | set(x.overrides), key=lambda o: o[0].start)
    m.deassigns = sorted(set(m.deassigns) | set(x.deassigns), key=lambda d: d.start)
    m.writes |= x.writes
    m.sensitivity |= x.sensitivity
    m.triggers |= x.triggers
    m.enablers |= x.enablers
    active = {r.span: r.active for r in m.stale_reads}
    for r in x.stale_reads:
        was = active.get(r.span, r.active)
        if FRESH in (was, r.active):
            active[r.span] = FRESH  # a fresh read is right in every state
        elif was != r.active:
            raise TransformError(
                model,
                f"the read of {x.name} at offset {r.span.start} sees different "
                "overrides under different generate configurations",
            )
        else:
            active[r.span] = r.active
    m.stale_reads = {StaleRead(sp, a) for sp, a in active.items()}


def analyze(
    path: Path, module: str, glbl: Path, choices: dict[str, list[str]] | None = None
) -> Analysis:
    """Analyse ``module`` in ``path`` (and every same-file helper module it instantiates)
    under every generate configuration, taking the union."""
    src = _Source(Path(path))
    merged: dict[str, dict[str, ForcedReg]] = {module: {}}
    ends: dict[str, int] = {}
    notes: list[str] = []
    elaborated: set[int] = set()
    instantiated: set[str] = set()
    for overrides in generate_configs(path, module, choices):
        _, inst = _compile(path, module, glbl, overrides)
        top = _Walker(module, inst, src)
        top.prescan()
        top.walk()
        for w in top.all():
            elaborated |= w.generate_blocks
            instantiated.add(w.defname)
            ends[w.defname] = src.char(w.body.definition.syntax.endmodule.location.offset)
            for x in w.regs.values():
                if not x.overrides:  # deassign-only here; see noop_deassigns below
                    x.sensitivity = set()
                    _merge_reg(
                        merged.setdefault(w.defname, {}).setdefault(x.name, _copy(x)), x, module
                    )
                    continue
                trig, en = w.lift(*w.trace(x.sensitivity))
                if not trig and x.name in w.always_forced:
                    raise w.err(
                        f"{x.name}: no trigger found (the forcing block has no sensitivity "
                        "list or its cone has no primitive input)"
                    )
                if not trig:
                    note = f"{w.defname}.{x.name}: forced only by initial blocks; no triggers"
                    if note not in notes:
                        notes.append(note)
                x.triggers, x.enablers = trig, en
                x.stale_reads = {StaleRead(sp, a) for sp, a in w._stale[x.name].items()}
                m = merged.setdefault(w.defname, {}).setdefault(x.name, _copy(x))
                _merge_reg(m, x, module)
        for w in top.all():  # notes are added while tracing, including the lifts above
            notes += [n for n in w.notes if n not in notes]
    subs = {n: r for n, r in merged.items() if n != module and r}
    _check_coverage(
        Path(path), module, src, {module: merged[module], **subs}, elaborated, instantiated
    )

    def build(name: str, regs: dict[str, ForcedReg]) -> Analysis:
        noop = sorted(d for x in regs.values() if not x.overrides for d in x.deassigns)
        for x in regs.values():
            if not x.overrides:
                notes.append(f"{name}.{x.name}: deassigned but never assigned; deassign is a no-op")
        forced = {n: x for n, x in regs.items() if x.overrides}
        return Analysis(name, Path(path), src.text, ends[name], forced, noop_deassigns=noop)

    a = build(module, merged[module])
    a.submodules = {n: build(n, r) for n, r in sorted(subs.items())}
    a.notes = sorted(set(notes))
    return a
