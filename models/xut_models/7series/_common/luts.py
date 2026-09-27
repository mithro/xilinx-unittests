# SPDX-License-Identifier: Apache-2.0
"""Clean-room golden models of the 7-series LUTs: LUT1-LUT6, LUT6_2 and CFGLUT5.

Written from UG953 v2026.1 only (CFGLUT5 pp. 348-349, LUT1 pp. 488-489, LUT2 pp. 491-492,
LUT3 pp. 494-495, LUT4 pp. 497-499, LUT5 pp. 500-502, LUT6 pp. 504-507, LUT6_2
pp. 509-512); no UNISIM source was consulted. Claim numbers match
catalog/7series/<PRIM>.overrides.yaml:

  LUTn    C1 logic table: O = INIT[{I<n-1>..I0}]    C2 INIT defaults to 0: O = 0
  LUT6_2  C1 O6 = INIT[{I5..I0}]    C2 O5 = INIT[{I4..I0}] (lower half; I5 unused)
          C3 INIT defaults to 0     C4 the p509 example 64'hFFFFFFFFFFFFFFFE (two ORs)
  CFGLUT5 C1 O6 follows the loaded INIT and I0-I4   C2 O5 is the 4-LUT output
          C3 CE High: an active CLK edge shifts CDI in   C4 CE Low: INIT unchanged
          C5 CDO cascades the shifted data (32 bits per LUT)
          C6 INIT is the start-up function   C7 IS_CLK_INVERTED=1: falling edge active

Provenance (AGENTS.md §8, spec §3):
- The LUTn and LUT6_2 logic tables are complete, so their outputs are ``doc:``.
- UG953 names no GSR effect on any LUT. While GSR is asserted a LUT keeps following its
  logic table, tagged ``inferred:`` (_GSR_LUT); that output credits no claim (ruling S44).
- The CFGLUT5 section refers to O5/O6 tables it does not contain and gives no shift
  direction, so the bit order is inferred (_O6_ORDER, _O5_ORDER, _SHIFT) and those bits
  are ``inferred:`` (a disagreement is a doc-gap).
- Ruling S52 (after S44): an output whose value depends on the inferred order credits no
  claim, even under a documented rule. The model therefore tracks what it knows
  *whatever the order*: the contents are known-uniform (all 0 or all 1) only when they
  were uniform at power-on and every bit shifted in since equals that value, or when the
  last 32 documented shifts all carried one value. Only then is a CFGLUT5 bit ``doc:348``
  and a CFGLUT5 claim credited; the contents computed under the inferred order are never
  used to decide that (ruling S53, correctness review M1).
- Ruling S55 (the general form of S32): a claim credits only on an event whose observable
  outcome depends on the claimed rule, i.e. a model that breaks the rule would show a
  different documented bit there. So C3/C7 credit only on the edge that sets ``known`` to a
  new value (a shift that changes nothing observable proves nothing), C4 only on a CE-Low
  edge whose CDI differs from ``known``, and C5 only on a CDO read after a 32-shift run
  flipped ``known`` from one uniform value to the other.
- Ruling S55, correctness re-review M7: "new" means new against ``_last_known``, the last
  order-free value, which a shift that loses ``known`` does not clear. Contents that were
  all ones, lost part-way and re-established as all ones show nothing a never-shifting
  model would not. A GSR loss resets ``_last_known`` to INIT's uniform value (None for a
  non-uniform INIT), the contents a never-shifting model shows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from xut_models.base import Model, ModelContractError, ModelUnsupported, Out, bit_attr

_GSR_LUT = (
    "inferred:UG953_names_no_GSR_effect_on_a_LUT;"
    "the_logic_table_is_taken_to_hold_while_GSR_is_asserted"
)
_O6_ORDER = (
    "inferred:CFGLUT5_p348_cites_O5/O6_tables_it_does_not_contain;"
    "O6_is_INIT[{I4..I0}]_as_in_the_LUT5_logic_table_(p501)"
)
_O5_ORDER = (
    "inferred:O5_is_the_4-LUT_output_(p348);"
    "O5_is_INIT[{I3..I0}]_(the_lower_half)_as_for_LUT6_2's_O5_(p509)"
)
_SHIFT = "inferred:p348_gives_no_shift_direction;CDI_enters_INIT[0]_and_INIT[31]_drives_CDO"
_GSR_CFG = (
    "inferred:UG953_names_no_GSR_effect_on_CFGLUT5;"
    "the_loaded_function_is_taken_to_be_kept_and_CE_shifts_to_continue"
)


def _init_value(prim: str, attrs: Mapping[str, str | int], width: int) -> int:
    v = bit_attr(attrs.get("INIT", 0))
    if not 0 <= v < 1 << width:
        raise ModelContractError(f"{prim}: INIT={attrs.get('INIT')!r} does not fit {width} bits")
    return v


class _Powered(Model):
    """Shared guards: the model API is used only after ``power_on`` (step-2 review R5)."""

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.pin = dict.fromkeys(self.inputs(), 0)
        self.gsr = 0
        self._powered_on = False

    def _require_power(self, what: str) -> None:
        if not self._powered_on:
            raise ModelContractError(f"{self.PRIM}: {what} before power_on")

    def _address(self, n: int) -> int:
        return sum(self.pin[f"I{i}"] << i for i in range(n))

    def power_on(self) -> None:
        self._powered_on = True
        self.gsr = 1

    def glbl(self, signal: str, value: int) -> None:
        self._require_power("glbl")
        if signal != "GSR":
            raise ModelUnsupported(f"{self.PRIM}: UG953 describes no {signal} effect")
        self.gsr = value

    def set_input(self, port: str, value: int) -> None:
        self._require_power("set_input")
        if port not in self.pin or port in self.CLOCKS:
            raise ModelContractError(f"{self.PRIM}: not a data input port: {port!r}")
        if value not in (0, 1):
            raise ModelContractError(f"{self.PRIM}: {port}={value!r} is not 0 or 1")
        self.pin[port] = value


class Lut(_Powered):
    """LUT1-LUT6: one output, O = INIT[{I<N-1>..I0}] (the logic table)."""

    N: ClassVar[int]  # number of inputs
    INTRO_PAGE: ClassVar[int]  # Introduction: INIT defaults to zero (a ground)
    TABLE_PAGE: ClassVar[int]  # Logic Table
    OUTPUTS: ClassVar[dict[str, int]] = {"O": 1}

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {f"I{i}": 1 for i in range(cls.N)}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.explicit_init = "INIT" in self.attrs
        self.init = _init_value(self.PRIM, self.attrs, 1 << self.N)

    def clock_edge(self, port: str, rising: bool) -> None:
        raise ModelContractError(f"{self.PRIM} has no clock: {port!r}")

    def _lookup(self, n: int, claim: int, default_claim: int) -> Out:
        """INIT bit ``{I<n-1>..I0}``: ``claim`` for an explicit INIT, ``default_claim``
        when INIT was not set (the documented zero default decides the bit)."""
        bit = str((self.init >> self._address(n)) & 1)
        if self.gsr:
            return Out(bit, _GSR_LUT)  # inferred: no claim (ruling S44)
        if not self.explicit_init:
            self.hit(f"{self.PRIM}.C{default_claim}")
            return Out(bit, f"doc:{self.INTRO_PAGE}")
        self.hit(f"{self.PRIM}.C{claim}")
        return Out(bit, f"doc:{self.TABLE_PAGE}")

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        return {"O": self._lookup(self.N, 1, 2)}


class DualLut(Lut):
    """LUT6_2: O6 = INIT[{I5..I0}], O5 = INIT[{I4..I0}] (p509-510)."""

    N = 6
    OUTPUTS: ClassVar[dict[str, int]] = {"O5": 1, "O6": 1}
    OR_EXAMPLE: ClassVar[int] = 0xFFFF_FFFF_FFFF_FFFE  # p509

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        o6 = self._lookup(6, 1, 3)
        o5 = self._lookup(5, 2, 3)
        if self.explicit_init and self.init == self.OR_EXAMPLE and not self.gsr:
            self.hit(f"{self.PRIM}.C4")
        return {"O5": o5, "O6": o6}


def _uniform_bit(value: int, width: int) -> int | None:
    """0 or 1 when ``value`` is all 0 or all 1 over ``width`` bits, else None."""
    return 0 if value == 0 else 1 if value == (1 << width) - 1 else None


class CfgLut5(_Powered):
    """CFGLUT5: a 32-bit INIT, read like a LUT5 (O6) and a LUT4 (O5), reloaded serially
    from CDI while CE is High, one bit per active CLK edge (p348-349)."""

    PAGE: ClassVar[int] = 348  # Introduction and ports: every CFGLUT5 doc: bit
    CLOCKS: ClassVar[tuple[str, ...]] = ("CLK",)
    OUTPUTS: ClassVar[dict[str, int]] = {"CDO": 1, "O5": 1, "O6": 1}
    WIDTH: ClassVar[int] = 32

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {"CDI": 1, "CE": 1, "CLK": 1, **{f"I{i}": 1 for i in range(5)}}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        super().__init__(attrs)
        self.init = _init_value(self.PRIM, self.attrs, self.WIDTH)
        #: INIT's uniform value (0 or 1), or None: the contents a never-shifting model shows
        self._init_uniform = _uniform_bit(self.init, self.WIDTH)
        self.inv_clk = bit_attr(self.attrs.get("IS_CLK_INVERTED", 0))
        self.contents = self.init  # under the inferred order (D5)
        self.shifts = 0  # documented shifts since power-on (none under GSR)
        #: the uniform value the contents hold whatever the shift order, or None
        self.known: int | None = None
        #: the last value ``known`` held; a shift that loses ``known`` keeps it (S55, M7)
        self._last_known: int | None = None
        #: (value, count) of the latest run of equal documented shifts
        self._run: tuple[int | None, int] = (None, 0)
        #: CDO now shows a bit a 32-shift run carried in over the opposite uniform value
        self._cascaded = False
        self._untouched = True  # no shift at all since power-on
        #: the contents depend on the GSR inference until 32 later documented shifts
        #: have replaced every bit (-1: never; else the shift count at that moment)
        self._gsr_mark = -1

    # -- helpers -----------------------------------------------------------------------
    def _gsr_dependent(self) -> bool:
        return self.gsr == 1 or (self._gsr_mark >= 0 and self.shifts - self._gsr_mark < self.WIDTH)

    def _order_free(self) -> bool:
        """What an output shows cannot depend on the inferred order (ruling S52)."""
        return self.known is not None and not self._gsr_dependent()

    def _credit(self, claim: int) -> None:
        if self._order_free():
            self.hit(f"{self.PRIM}.C{claim}")

    def _read(self, index: int, order: str, claim: int | None) -> Out:
        bit = str((self.contents >> index) & 1)
        if self._gsr_dependent():
            return Out(bit, _GSR_CFG)  # an inferred rule decides it: no claim (S44)
        if claim is not None:
            self._credit(claim)
        return Out(bit, f"doc:{self.PAGE}" if self.known is not None else order)

    def _lose_order_free_state(self) -> None:
        """A GSR loss: what the contents were is itself an inference now, so the only
        value a model that never shifted would still show is INIT's own."""
        self.known = None
        self._last_known = self._init_uniform
        self._run = (None, 0)
        self._cascaded = False

    # -- Model API ---------------------------------------------------------------------
    def power_on(self) -> None:
        super().power_on()
        self.contents = self.init
        self.known = self._last_known = self._init_uniform
        if self.known is not None:  # INIT is the start-up function (p349); uniform only
            self.hit(f"{self.PRIM}.C6")

    def glbl(self, signal: str, value: int) -> None:
        super().glbl(signal, value)
        if not value:
            return
        # "keep the contents" and "reload INIT" agree only if nothing was shifted since
        # power-on, or the contents are known-uniform with INIT's own uniform value.
        same = self._untouched or (self.known is not None and self.known == self._init_uniform)
        if not same:
            self._gsr_mark = self.shifts
            self._lose_order_free_state()

    def clock_edge(self, port: str, rising: bool) -> None:
        self._require_power("clock_edge")
        if port not in self.CLOCKS:
            raise ModelContractError(f"{self.PRIM}: not a clock port: {port!r}")
        if rising == bool(self.inv_clk):
            return  # not the active edge
        if not self.pin["CE"]:
            if self.known is not None and self.pin["CDI"] != self.known:
                self._credit(4)  # CE Low held back a shift that would have shown (S55)
            return
        cdi = self.pin["CDI"]
        self.contents = ((self.contents << 1) | cdi) & ((1 << self.WIDTH) - 1)
        self._untouched = False
        if self.gsr:
            self._gsr_mark = self.shifts  # shifting under GSR is itself an inference
            self._lose_order_free_state()
            return
        self.shifts += 1
        before = self.known
        value, count = self._run
        self._run = (cdi, count + 1 if value == cdi else 1)
        if self.known is not None and cdi != self.known:
            self.known = None  # _last_known keeps the old value (M7)
            self._cascaded = False
        if self._run[1] >= self.WIDTH:
            self.known = cdi  # 32 equal shifts replace every bit, whatever the order
        if before is None and self.known is not None:
            # known re-established. It is new only against the last order-free value: a
            # model that did not shift, or shifted on the wrong edge, shows that one (S55,
            # M7). With none (a non-uniform INIT) it shows a non-uniform INIT, so any
            # uniform value is new.
            if self._last_known != cdi:
                self._credit(3)
                if self.inv_clk:
                    self._credit(7)
                if self._last_known is not None:
                    self._cascaded = True  # CDO flipped from the old uniform value
            self._last_known = cdi

    def outputs(self) -> dict[str, Out]:
        self._require_power("outputs")
        # C5 is the cascade: CDO now carries a bit that came in on CDI (32 bits per LUT) and
        # differs from what the loaded contents showed, so a stuck CDO would fail (S55).
        cascade = 5 if self._cascaded else None
        return {
            "CDO": self._read(self.WIDTH - 1, _SHIFT, cascade),
            "O5": self._read(self._address(4), _O5_ORDER, 2),
            "O6": self._read(self._address(5), _O6_ORDER, 1),
        }
