# SPDX-License-Identifier: Apache-2.0
"""Clean-room golden model of the 7-series SDR flip-flops FDRE, FDSE, FDCE, FDPE.

Written from UG953 v2026.1 only (FDCE pp. 369-370, FDPE pp. 372-373,
FDRE pp. 375-376, FDSE pp. 378-379); no UNISIM source was consulted.
Claim numbers match catalog/7series/<PRIM>.overrides.yaml:

  C1 capture   CE High, control inactive: Q <- D at the active clock edge
  C2 ce_hold   CE Low: clock edges are ignored
  C3 control   an active control overrides all other inputs
               (R/S at the next active edge; CLR/PRE at once)
  C4 gsr_init  GSR active: Q = INIT
  C5 inv_c     IS_C_INVERTED=1: the falling edge is the active edge
  C6 inv_ctrl  IS_<ctrl>_INVERTED=1: the control is active-Low
  C7 inv_d     IS_D_INVERTED=1: D is inverted

Behaviour UG953 does not state is tagged ``inferred:``. Ruling S30: an async
control (CLR/PRE) that is active while GSR is asserted, and disagrees with
GSR's INIT, is not left as a don't-care -- a ``-`` bit needs ``doc:<page>``
provenance (spec §5.3), and UG953 never declares *this* conflict undefined.
Instead the control's forced value is taken to win (``inferred:``), and the
C3 (``control``) claim is still hit.

Ruling S32: a claim is hit only when its behaviour actually decides the
output at that event (never from a bare probe, and never redundantly from an
async control an earlier event already forced), and every ``doc:`` output
cites the page of the rule that produced it -- ``PAGE`` for a capture, a CE
hold, a control force or a GSR->INIT sample, ``ATTR_PAGE`` for one shaped by
an inversion attribute (C5/C6/C7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from xut_models.base import Model, ModelContractError, ModelUnsupported, Out, bit_attr

_CLAIM = {
    "capture": 1,
    "ce_hold": 2,
    "control": 3,
    "gsr_init": 4,
    "inv_c": 5,
    "inv_ctrl": 6,
    "inv_d": 7,
}
_GSR_EDGE = (
    "inferred:UG953_describes_GSR_as_holding_INIT_while_active;"
    "clock_edges_during_GSR_are_taken_to_be_ignored"
)
_GSR_VS_CTRL = (
    "inferred:UG953_says_an_active_CLR/PRE_overrides_all_other_inputs_"
    "(p369/p372)_but_does_not_name_GSR;_the_control_is_taken_to_win"
)
_INIT_BEFORE_POWER_ON = "inferred:state_before_power-on_is_not_described;INIT_assumed"


class SdrFlop(Model):
    CTRL: ClassVar[str]  # R | S | CLR | PRE
    CTRL_VALUE: ClassVar[int]  # the value the control drives onto Q
    CTRL_ASYNC: ClassVar[bool]
    INIT_DEFAULT: ClassVar[int]  # from the UG953 attribute table
    PAGE: ClassVar[int]  # Introduction / Logic Table page
    ATTR_PAGE: ClassVar[int]  # Available Attributes page
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {"C": 1, "CE": 1, "D": 1, cls.CTRL: 1}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        a = self.attrs
        self.init = bit_attr(a.get("INIT", self.INIT_DEFAULT))
        self.inv_c = bit_attr(a.get("IS_C_INVERTED", 0))
        self.inv_d = bit_attr(a.get("IS_D_INVERTED", 0))
        self.inv_ctrl = bit_attr(a.get(f"IS_{self.CTRL}_INVERTED", 0))
        self.pin = dict.fromkeys(self.inputs(), 0)
        self.gsr = 0
        self.q = Out(str(self.init), _INIT_BEFORE_POWER_ON)

    # -- helpers ------------------------------------------------------------------
    def _hit(self, role: str) -> None:
        self.hit(f"{self.PRIM}.C{_CLAIM[role]}")

    def _doc(self, bit: int, page: int | None = None) -> Out:
        return Out(str(bit), f"doc:{page or self.PAGE}")

    def _ctrl_active(self) -> bool:
        """A pure predicate: no hit. Whether the active-Low inversion (C6) actually
        decided anything is for the caller to say, at the point it acts on this."""
        return bool(self.pin[self.CTRL] ^ self.inv_ctrl)

    def _under_gsr(self) -> Out:
        if self.CTRL_ASYNC and self._ctrl_active() and self.init != self.CTRL_VALUE:
            self._hit("control")  # the two documented behaviours disagree: control wins
            return Out(str(self.CTRL_VALUE), _GSR_VS_CTRL)
        self._hit("gsr_init")  # (when they agree, both documented rules give INIT)
        return self._doc(self.init)

    def _force(self, *, inverted: bool = False) -> None:
        """Called only where the control's activity actually decides Q: an async
        control going active, or a synchronous one at its active edge. ``inverted``
        is set by the caller when *that* decision also depended on IS_C_INVERTED
        (an inverted active edge); the control's own inversion is checked here."""
        attr = inverted or bool(self.inv_ctrl)
        self.q = self._doc(self.CTRL_VALUE, self.ATTR_PAGE if attr else None)
        self._hit("control")
        if self.inv_ctrl:
            self._hit("inv_ctrl")

    # -- Model API ------------------------------------------------------------------
    def power_on(self) -> None:
        self.gsr = 1
        self.q = self._under_gsr()

    def glbl(self, signal: str, value: int) -> None:
        if signal != "GSR":
            raise ModelUnsupported(f"{self.PRIM}: UG953 describes only GSR for this primitive")
        self.gsr = value
        if value:
            self.q = self._under_gsr()
        elif self.CTRL_ASYNC and self._ctrl_active():
            self._force()

    def set_input(self, port: str, value: int) -> None:
        if port not in self.pin:
            raise ModelContractError(f"{self.PRIM}: not an input port: {port!r}")
        self.pin[port] = value
        if port != self.CTRL or not self.CTRL_ASYNC:
            return
        if self.gsr:
            self.q = self._under_gsr()
        elif self._ctrl_active():
            self._force()

    def clock_edge(self, port: str, rising: bool) -> None:
        if port not in self.CLOCKS:
            raise ModelContractError(f"{self.PRIM}: not a clock port: {port!r}")
        if rising == bool(self.inv_c):
            return  # not the active edge
        if self.gsr:
            # An edge that would be ignored anyway (CE Low, control inactive) needs no
            # retag: UG953 already accounts for it without leaning on the GSR inference
            # (spec §3/§8: keep every disagreement live, never mask it with a needless
            # ``inferred:``).
            if self.pin["CE"] or self._ctrl_active():
                self.q = Out(self.q.bits, _GSR_EDGE)
            return
        if self._ctrl_active():
            if not self.CTRL_ASYNC:
                # Only a synchronous control's force is decided by *this* edge; an
                # async control was already forced the moment it went active (via
                # set_input/glbl), so a later edge decides nothing new here.
                if self.inv_c:
                    self._hit("inv_c")
                self._force(inverted=bool(self.inv_c))
            return
        if not self.pin["CE"]:
            self._hit("ce_hold")
            return
        if self.inv_c:
            self._hit("inv_c")
        if self.inv_d:
            self._hit("inv_d")
        attr = self.inv_c or self.inv_d
        self.q = self._doc(self.pin["D"] ^ self.inv_d, self.ATTR_PAGE if attr else None)
        self._hit("capture")

    def outputs(self) -> dict[str, Out]:
        return {"Q": self.q}
