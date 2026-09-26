# SPDX-License-Identifier: Apache-2.0
"""Which testbench nets can float z into an input of a primitive (Task 15 re-review N1,
ruling S47.3).

The z-compare rewrite (ruling S38) is exact only when every input of the model is driven.
``sv_instances`` already refuses an input left open or tied to a z constant; this module
refuses the rest of what is visible statically: an input connected to a net that nothing
drives. It works on the elaborated design (pyslang), so a net bound by ``.*``, an implicit
net, and a net reached through a submodule's ports are all seen.

A net **can float** (be z at run time) when every one of its drivers can:

* no driver at all (a declared wire never assigned, an implicit net, an input port of a
  top module, or an input port its instance leaves open) floats: it is a *root*;
* ``tri0``/``tri1``/``supply0``/``supply1``/``trireg`` nets never float;
* a continuous assign (or a net declaration's initialiser) floats when its right-hand side
  can: through a net reference, a bit or part select, a concatenation or replication, a
  type conversion or either branch of ``?:``, or a constant holding a z bit. An operator
  or a system call never yields z;
* an output port of a submodule floats when the port's net inside it can;
* a gate that can output z (``bufif``, ``notif``, the MOS and ``tran`` switches) and an
  ``inout`` port connection are assumed to float (fail closed); other gates, UDPs and
  procedural ``force``/``assign`` never do;
* a call of a user function is not followed: it is reported as unverifiable (fail closed).

Only nets matter: a variable nothing writes holds x, not z, and ``x === 1'bz`` is false
in the original exactly as the rewritten constant is.
"""

from __future__ import annotations

import pyslang

_EK = pyslang.ast.ExpressionKind
_NEVER_Z_NETS = frozenset({"tri0", "tri1", "supply0", "supply1", "trireg"})
#: gates whose output can be z (IEEE 1800-2017 §28.5-§28.9)
_Z_GATES = frozenset(
    {
        "bufif0", "bufif1", "notif0", "notif1", "nmos", "pmos", "rnmos", "rpmos",
        "cmos", "rcmos", "tran", "rtran", "tranif0", "tranif1", "rtranif0", "rtranif1",
    }
)  # fmt: skip
_PASS = (_EK.ElementSelect, _EK.RangeSelect, _EK.MemberAccess)
_LITERALS = (_EK.IntegerLiteral, _EK.UnbasedUnsizedIntegerLiteral)


def _has_z(value: object) -> bool:
    """A constant (``ConstantValue``, or a literal's ``SVInt``) with a z bit."""
    if value is None:
        return False
    unknown = value.hasUnknown  # type: ignore[attr-defined]
    return bool(unknown() if callable(unknown) else unknown) and "z" in str(value).lower()


def _refs(e: object) -> list[object]:
    """The symbols lvalue ``e`` writes: through selects (never their index expressions),
    member accesses, conversions and concatenations; anything else is walked whole."""
    k = e.kind  # type: ignore[attr-defined]
    if k in (_EK.NamedValue, _EK.HierarchicalValue):
        return [e.symbol]  # type: ignore[attr-defined]
    if k in _PASS:
        return _refs(e.value)  # type: ignore[attr-defined]
    if k == _EK.Conversion:
        return _refs(e.operand)  # type: ignore[attr-defined]
    if k == _EK.Concatenation:
        return [s for x in e.operands for s in _refs(x)]  # type: ignore[attr-defined]
    out: list[object] = []

    def visit(x: object) -> bool:
        if isinstance(
            x, pyslang.ast.NamedValueExpression | pyslang.ast.HierarchicalValueExpression
        ):
            out.append(x.symbol)
        return True

    e.visit(visit)  # type: ignore[attr-defined]
    return out


class Nets:
    """The drivers of every net of an elaborated design (``comp.getRoot()``)."""

    def __init__(self, root: object) -> None:
        #: net path -> its drivers: ("expr", expression) | ("port", internal symbol) |
        #: ("z", why) | ("fixed", why)
        self.drivers: dict[str, list[tuple[str, object]]] = {}
        #: the net of an input port -> its instance's connection (None: left open)
        self.inputs: dict[str, object | None] = {}
        self.nets: dict[str, object] = {}
        self._memo: dict[str, list[str]] = {}
        tops = {i.hierarchicalPath for i in root.topInstances}  # type: ignore[attr-defined]
        root.visit(lambda o: self._collect(o, tops))  # type: ignore[attr-defined]

    def _add(self, lhs: object, driver: tuple[str, object]) -> None:
        for s in _refs(lhs):
            self.drivers.setdefault(s.hierarchicalPath, []).append(driver)

    def _collect(self, o: object, tops: set[str]) -> bool:
        ast = pyslang.ast
        if isinstance(o, ast.NetSymbol):
            self.nets[o.hierarchicalPath] = o
            if o.initializer is not None:
                self.drivers.setdefault(o.hierarchicalPath, []).append(("expr", o.initializer))
        elif isinstance(o, ast.ContinuousAssignSymbol):
            a = o.assignment
            self._add(a.left, ("expr", a.right))
        elif isinstance(o, ast.ProceduralAssignStatement):
            self._add(o.assignment.left, ("fixed", "a procedural assign or force"))
        elif isinstance(o, ast.PrimitiveInstanceSymbol):
            gate = o.primitiveType.name
            drv = ("z", f"gate {gate}") if gate in _Z_GATES else ("fixed", f"gate {gate}")
            for e in o.portConnections:
                if e.kind == _EK.Assignment:
                    self._add(e.left, drv)
        elif isinstance(o, ast.InstanceSymbol):
            top = o.hierarchicalPath in tops
            for c in o.portConnections:
                internal = c.port.internalSymbol
                e = c.expression
                if c.port.direction == ast.ArgumentDirection.In:
                    if internal is not None:
                        self.inputs[internal.hierarchicalPath] = None if top else e
                elif e is not None and e.kind == _EK.Assignment:
                    if c.port.direction == ast.ArgumentDirection.Out and internal is not None:
                        self._add(e.left, ("port", internal))
                    else:
                        self._add(e.left, ("z", f"inout port {o.hierarchicalPath}.{c.port.name}"))
        return True

    def floats(self, e: object | None) -> list[str]:
        """Why expression ``e`` can be z: the root nets that have
        no driver (their paths), or a description of another z source; empty if it
        cannot."""
        if e is None:
            return []
        k = e.kind  # type: ignore[attr-defined]
        if k in (_EK.NamedValue, _EK.HierarchicalValue):
            s = e.symbol  # type: ignore[attr-defined]
            if isinstance(s, pyslang.ast.NetSymbol):
                return self.net(s.hierarchicalPath)
            if isinstance(s, pyslang.ast.ParameterSymbol) and _has_z(s.value):
                return [f"parameter {s.name} holds z"]
            return []
        if k in _LITERALS:
            return ["a z constant"] if _has_z(e.value) else []  # type: ignore[attr-defined]
        if k in _PASS:
            return self.floats(e.value)  # type: ignore[attr-defined]
        if k == _EK.Conversion:
            return self.floats(e.operand)  # type: ignore[attr-defined]
        if k == _EK.Concatenation:
            return [w for x in e.operands for w in self.floats(x)]  # type: ignore[attr-defined]
        if k == _EK.Replication:
            return self.floats(e.concat)  # type: ignore[attr-defined]
        if k == _EK.ConditionalOp:
            return [*self.floats(e.left), *self.floats(e.right)]  # type: ignore[attr-defined]
        if k == _EK.Call and not e.isSystemCall:  # type: ignore[attr-defined]
            return [f"a call of {e.subroutineName} (not followed)"]  # type: ignore[attr-defined]
        return []  # an operator (or a system call) never yields z

    def net(self, path: str) -> list[str]:
        """Why net ``path`` can be z (``floats``); a net in a driver loop counts as a root."""
        if path in self._memo:
            return self._memo[path]
        self._memo[path] = [path]  # in progress: a loop without another driver floats
        sym = self.nets.get(path)
        if sym is not None and sym.netType.name in _NEVER_Z_NETS:  # type: ignore[attr-defined]
            self._memo[path] = []
            return []
        drivers = list(self.drivers.get(path, []))
        if path in self.inputs:
            conn = self.inputs[path]
            drivers.append(("expr", conn) if conn is not None else ("open", None))
        why: list[str] = []
        for kind, what in drivers:
            if kind == "fixed":
                why = []
                break
            if kind == "z":
                got = [str(what)]
            elif kind == "open":
                got = [path]
            elif kind == "port":
                got = (
                    self.net(what.hierarchicalPath)
                    if isinstance(what, pyslang.ast.NetSymbol)
                    else []
                )  # type: ignore[attr-defined]
            else:
                got = self.floats(what)
            if not got:  # one driver that never floats keeps the net out of z
                why = []
                break
            why += [w for w in got if w not in why]
        else:
            if not drivers:
                why = [path]
        self._memo[path] = why
        return why
