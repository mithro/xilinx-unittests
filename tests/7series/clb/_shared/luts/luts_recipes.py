# SPDX-License-Identifier: Apache-2.0
"""Stimulus recipes shared by the luts work unit (LUT1-LUT6, LUT6_2, CFGLUT5).

Each recipe takes a GenContext and a LutKind and yields .xvec files built with VecBuilder,
so every file satisfies the spec §5.1 class rules by construction. Recipes only drive
inputs and place samples: expected values come from the golden model (python runner).

INIT sampling (spec §4.2, recorded per test in test.yaml ``attr_sampling``):
- an INIT of at most 4 bits (LUT1, LUT2) is covered exhaustively, every value;
- a wider INIT by its boundary values (all 0, all 1) and walking ones and walking zeros
  (every bit position) in L2.init_sweep, and by ``RANDOM_INITS`` seeded random values
  (the test's seed) in L2.init_random;
- every kind also by the input projections (INIT such that O = I<j>, and complements) in
  L1.projections, which pin the logic table's input-to-address order one input at a time.
Configurations are read with an exhaustive sweep of the inputs (``sweep``), except
where a recipe says otherwise (``l1_cdo_cascade`` reads CDO after every shift).

Ruling S52 (CFGLUT5): a read whose value depends on the inferred bit order credits no
claim, and a configuration credits a claim only when it passes on a simulator. So every
CFGLUT5 claim and bin has a *pure* configuration, all of whose samples are
order-independent (known-uniform contents): ``l1_default_init`` and ``l1_edge_polarity``.
The unit's guard ``test_every_exercised_bin_has_a_pure_configuration`` checks it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xut.formats.xvec import Vec

Gen = Iterator["Vec"]

RANDOM_INITS = 16
#: L2.random (CFGLUT5): configurations, steps per configuration, and the chance that a
#: step is a one-bit reload rather than a read, and that such a reload has CE High
RANDOM_CONFIGS = 8
RANDOM_STEPS = 400
RELOAD_P = 0.4
CE_HIGH_P = 0.8
#: L1.ce_low_holds: the CDI values driven through CE-Low cycles
CE_LOW_CDI = (1, 0, 1, 1, 0, 1, 0, 0)


@dataclass(frozen=True)
class LutKind:
    prim: str
    n: int  # LUT inputs I0..I<n-1>
    width: int  # INIT bits
    outputs: tuple[str, ...]
    reconfig: bool  # CFGLUT5: CDI/CE/CLK reload INIT at run time


KINDS = {
    **{f"LUT{n}": LutKind(f"LUT{n}", n, 1 << n, ("O",), False) for n in range(1, 7)},
    "LUT6_2": LutKind("LUT6_2", 6, 64, ("O5", "O6"), False),
    "CFGLUT5": LutKind("CFGLUT5", 5, 32, ("CDO", "O5", "O6"), True),
}
BIN = ("1'b0", "1'b1")


def lit(k: LutKind, value: int) -> str:
    """``value`` as INIT's sized hex literal (``64'h000000000000000f``)."""
    return f"{k.width}'h{value:0{(k.width + 3) // 4}x}"


def ones(k: LutKind) -> int:
    return (1 << k.width) - 1


def projection(k: LutKind, j: int) -> int:
    """The INIT for which the addressed bit equals input I<j> (O = I<j>)."""
    return sum(1 << a for a in range(1 << k.n) if (a >> j) & 1) & ones(k)


def init_samples(k: LutKind) -> list[tuple[str, int]]:
    """``(name, INIT)`` per spec §4.2: every value of a <= 4-bit INIT; otherwise the
    boundaries, walking ones and walking zeros (``random_inits`` adds the random ones)."""
    if k.width <= 4:
        return [(f"v{v:x}", v) for v in range(1 << k.width)]
    out = [("zeros", 0), ("ones", ones(k))]
    out += [(f"w1_{i}", 1 << i) for i in range(k.width)]
    return out + [(f"w0_{i}", ones(k) ^ (1 << i)) for i in range(k.width)]


def random_inits(k: LutKind, rng: Random) -> list[tuple[str, int]]:
    """RANDOM_INITS distinct seeded random values, none a boundary or walking value."""
    out: list[tuple[str, int]] = []
    seen = {v for _, v in init_samples(k)}
    while len(out) < RANDOM_INITS:
        v = rng.getrandbits(k.width)
        if v not in seen:
            seen.add(v)
            out.append((f"r{len(out)}", v))
    return out
