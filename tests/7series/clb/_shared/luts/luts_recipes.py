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

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import partial
from random import Random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xut.formats.xvec import Vec
    from xut.stimgen import GenContext

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


class LutDriver:
    """One configuration of a LUT kind, driven by address."""

    def __init__(self, ctx: GenContext, k: LutKind, cfg: str, **attrs: str) -> None:
        self.k = k
        self.b = ctx.dut(cfg, **attrs)

    def address(self, a: int) -> None:
        """All LUT inputs at once (one atomic input change, ruling S6)."""
        self.b.set(**{f"I{i}": (a >> i) & 1 for i in range(self.k.n)})

    def read(self, a: int) -> None:
        self.address(a)
        self.b.sample()

    def sweep(self) -> None:
        """Every address in binary order, then back to 0: each input is driven both
        ways by a real ``set`` (the power-on 0 does not count, ruling S19)."""
        self.b.sample()  # the power-on read: address 0 with nothing driven yet
        for a in range(1, 1 << self.k.n):
            self.read(a)
        self.read(0)

    def walk(self, rng: Random, steps: int) -> None:
        """Random addresses: several inputs change at once, in random order."""
        for _ in range(steps):
            self.read(rng.randrange(1 << self.k.n))

    def build(self) -> Vec:
        return self.b.build()


class CfgLutDriver(LutDriver):
    """A CFGLUT5 configuration: LUT reads plus serial reloads through CDI/CE/CLK."""

    def shift(self, bits: Iterable[int], *, ce: int = 1, sample: bool = False) -> None:
        """One full CLK cycle per bit (rise, then fall: one active edge whatever
        IS_CLK_INVERTED is), with CE and CDI set before it."""
        for bit in bits:
            self.b.set(CE=ce, CDI=bit)
            self.b.cycle("CLK", sample=sample)

    def load(self, value: int) -> None:
        """Shift in all 32 bits of ``value``, most significant first, then drop CE.
        Under any shift direction, 32 shifts replace the whole INIT (p348: 32 bits per
        LUT); ``value`` ends up in INIT as written only under the model's inferred order."""
        self.shift([(value >> i) & 1 for i in reversed(range(self.k.width))])
        self.b.set(CE=0)


def _config(ctx: GenContext, k: LutKind, cfg: str, init: int | None, **extra: str) -> LutDriver:
    """A driver for one configuration (INIT unset when ``init`` is None)."""
    cls = CfgLutDriver if k.reconfig else LutDriver
    attrs = {} if init is None else {"INIT": lit(k, init)}
    return cls(ctx, k, cfg, **attrs, **extra)


def _cfglut(ctx: GenContext, k: LutKind, cfg: str, init: int, **extra: str) -> CfgLutDriver:
    """A CFGLUT5 driver with an explicit INIT (the CFGLUT5-only recipes)."""
    return CfgLutDriver(ctx, k, cfg, INIT=lit(k, init), **extra)


# -- every kind --------------------------------------------------------------------------


def l0_smoke(ctx: GenContext, k: LutKind) -> Gen:
    """Elaborates with the default and two sampled INITs, one sweep each (CFGLUT5: both
    IS_CLK_INVERTED values set explicitly, and one reload bit)."""
    rnd = ctx.rng.getrandbits(k.width)
    cfgs = [("default", None, {}), ("ones", ones(k), {}), ("rand", rnd, {})]
    if k.reconfig:
        cfgs[1] = ("ones_clk0", ones(k), {"IS_CLK_INVERTED": BIN[0]})
        cfgs[2] = ("rand_clk1", rnd, {"IS_CLK_INVERTED": BIN[1]})
    for cfg, init, extra in cfgs:
        f = _config(ctx, k, cfg, init, **extra)
        f.sweep()
        if isinstance(f, CfgLutDriver):
            f.shift([1], sample=True)
            f.b.set(CE=0, CDI=0)
            f.b.sample()
        yield f.build()


def l0_illegal_init(ctx: GenContext, k: LutKind) -> Gen:
    """INIT with x digits is not a HEX value (UG953 attribute table): expect=reject."""
    b = ctx.dut(
        "init_x",
        allow_illegal=True,
        expect="reject",
        illegal=["INIT"],
        INIT=f"{k.width}'b{'x' * k.width}",
    )
    b.sample()
    yield b.build()


def l1_default_init(ctx: GenContext, k: LutKind) -> Gen:
    f = _config(ctx, k, "default", None)
    f.sweep()
    yield f.build()


def l1_projections(ctx: GenContext, k: LutKind) -> Gen:
    """O = I<j> and O = ~I<j> for every input: a swapped input pair fails at once."""
    for j in range(k.n):
        for name, init in ((f"p{j}", projection(k, j)), (f"n{j}", ones(k) ^ projection(k, j))):
            f = _config(ctx, k, name, init)
            f.sweep()
            yield f.build()


def l1_gsr_transparent(ctx: GenContext, k: LutKind) -> Gen:
    """A GSR pulse while the inputs move: the model infers the table still holds
    (UG953 names no GSR effect on a LUT), so a disagreement is a doc-gap finding."""
    f = _config(ctx, k, "rand", ctx.rng.getrandbits(k.width))
    for a in (0, (1 << k.n) - 1):
        f.read(a)
    f.b.glbl("GSR", 1)
    f.b.sample()
    f.walk(ctx.rng, 8)
    f.b.glbl("GSR", 0)
    f.b.sample()
    f.sweep()
    yield f.build()


def l2_init_sweep(ctx: GenContext, k: LutKind) -> Gen:
    """Spec §4.2 INIT sampling, each value read exhaustively."""
    for name, init in init_samples(k):
        f = _config(ctx, k, name, init)
        f.sweep()
        yield f.build()


def l2_init_random(ctx: GenContext, k: LutKind) -> Gen:
    """Seeded random INITs, each swept and then read at 2**n random addresses."""
    for name, init in random_inits(k, ctx.rng):
        f = _config(ctx, k, name, init)
        f.sweep()
        f.walk(ctx.rng, 1 << k.n)
        yield f.build()


# -- LUT6_2 ------------------------------------------------------------------------------

#: LUT6_2's O5 reads the lower half of INIT (p509)
O5_HALF = (1 << 32) - 1


def l1_o5_lower_half(ctx: GenContext, k: LutKind) -> Gen:
    """For each {I4..I0}, I5 low then high: O5 must not move; O6 moves to the upper half."""
    upper = ones(k) ^ O5_HALF
    p0 = projection(k, 0)
    cases = (
        ("lo_p0_hi_n0", (p0 & O5_HALF) | ((ones(k) ^ p0) & upper)),  # O5 = I0; O6 = I0 ^ I5
        ("lo_zero_hi_ones", upper),  # O5 = 0; O6 = I5
        ("rand", ctx.rng.getrandbits(k.width)),
    )
    half = 1 << (k.n - 1)
    for name, init in cases:
        f = _config(ctx, k, name, init)
        f.b.sample()
        for a in range(half):
            f.read(a)
            f.read(a | half)
        f.read(0)
        yield f.build()


def l1_doc_example(ctx: GenContext, k: LutKind) -> Gen:
    """p509: INIT=64'hFFFFFFFFFFFFFFFE gives a 6-input OR on O6 and a 5-input OR on O5."""
    f = _config(ctx, k, "or6_or5", ones(k) ^ 1)
    f.sweep()
    yield f.build()


# -- CFGLUT5 -----------------------------------------------------------------------------


def l1_edge_polarity(ctx: GenContext, k: LutKind) -> Gen:
    """The pure CFGLUT5 test (ruling S52): every sample is order-independent.

    For each IS_CLK_INVERTED value and each uniform INIT: sweep; apply only the
    *inactive* edge with CE High and the opposite CDI, then sweep (and CDO): nothing may
    change (a simulator that shifts on both edges, or ignores IS_CLK_INVERTED, fails a
    documented bit here); take the active edge with CE Low (C4); shift the opposite value
    in 32 times with no read in between, then sweep: the whole function has flipped,
    whatever the shift direction (C3, C5, C7 when inverted). The CE-Low active edge sees
    the opposite CDI, so a simulator that ignores CE would flip a documented bit (S55)."""
    for inverted in (0, 1):
        for init in (0, ones(k)):
            bit = init & 1
            f = _cfglut(
                ctx,
                k,
                f"clk{inverted}_{'ones' if bit else 'zeros'}",
                init,
                IS_CLK_INVERTED=BIN[inverted],
            )
            f.sweep()
            if inverted:  # rising is inactive: CE High, opposite CDI, rise only
                f.b.set(CE=1, CDI=1 - bit)
                f.b.edge("CLK", True)
                f.b.set(CE=0)
                f.sweep()
                f.b.edge("CLK", False)  # the active edge, CE Low: holds
            else:  # rising is active: take it with CE Low (opposite CDI), then the fall
                f.b.set(CDI=1 - bit)  # so a CE-ignoring simulator would shift (S55)
                f.b.edge("CLK", True)
                f.b.set(CE=1, CDI=1 - bit)
                f.b.edge("CLK", False)
                f.b.set(CE=0)
                f.sweep()
            f.b.sample()
            f.shift([1 - bit] * k.width)
            f.b.set(CE=0, CDI=0)
            f.sweep()
            yield f.build()


def l1_ce_low_holds(ctx: GenContext, k: LutKind) -> Gen:
    """CE Low: CDI toggles and CLK runs, but the function and CDO stay put. Only the
    all-ones configuration credits C4: the others' reads depend on the inferred bit
    order (ruling S52)."""
    cases = (("rand", ctx.rng.getrandbits(k.width)), ("p0", projection(k, 0)), ("ones", ones(k)))
    for name, init in cases:
        f = _cfglut(ctx, k, name, init)
        f.sweep()
        f.shift(CE_LOW_CDI, ce=0, sample=True)
        f.sweep()
        yield f.build()


def l1_reconfigure(ctx: GenContext, k: LutKind) -> Gen:
    """Load a new function through CDI and read it back exhaustively. The first three
    test the inferred order; ``ones_to_zero`` is order-independent throughout."""
    pairs = [
        ("zero_to_rand", 0, ctx.rng.getrandbits(k.width)),
        ("ones_to_p2", ones(k), projection(k, 2)),
        ("rand_to_rand", ctx.rng.getrandbits(k.width), ctx.rng.getrandbits(k.width)),
        ("ones_to_zero", ones(k), 0),
    ]
    for name, init, new in pairs:
        f = _cfglut(ctx, k, name, init)
        f.sweep()
        f.load(new)
        f.sweep()
        yield f.build()


def l1_cdo_cascade(ctx: GenContext, k: LutKind) -> Gen:
    """Two chains of shifts, CDO sampled after each, then a sweep: the old INIT leaves on
    CDO, then the first shifted-in bits follow ``k.width`` shifts later. Random data tests
    the inferred order (which INIT bit reaches CDO first); ``ones_zeros_ones`` flips the
    uniform contents twice."""
    w = k.width
    cases = (
        ("rand", ctx.rng.getrandbits(w), [ctx.rng.randrange(2) for _ in range(2 * w)]),
        ("ones_zeros_ones", ones(k), [0] * w + [1] * w),
    )
    for name, init, bits in cases:
        f = _cfglut(ctx, k, name, init)
        f.b.sample()
        f.shift(bits, sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_partial_shift(ctx: GenContext, k: LutKind) -> Gen:
    """Fewer than ``k.width`` shifts leave a mix of old and new bits (order inferred)."""
    for count in (1, 5, k.width // 2, k.width - 1):
        f = _cfglut(ctx, k, f"k{count}", ctx.rng.getrandbits(k.width))
        f.shift([ctx.rng.randrange(2) for _ in range(count)])
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_is_clk_inverted(ctx: GenContext, k: LutKind) -> Gen:
    """IS_CLK_INVERTED=1: samples after each rise show no shift, after each fall one. The
    intermediate samples depend on the inferred order; ``l1_edge_polarity`` is the pure
    test of the same claim, and the only one that credits C7: here a rise-shifting
    simulator differs only on order-dependent samples, so this test exercises C7 without
    crediting it (ruling S52)."""
    for name, init in (("zeros", 0), ("ones", ones(k))):
        f = _cfglut(ctx, k, name, init, IS_CLK_INVERTED=BIN[1])
        f.read(k.width - 1)
        f.shift([1 - (init & 1)] * k.width, sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_shift_while_reading(ctx: GenContext, k: LutKind) -> Gen:
    """An address is held while 8 bits shift in, 4 times: the function changes at run
    time while it is being used."""
    for name in ("a", "b"):
        f = _cfglut(ctx, k, name, ctx.rng.getrandbits(k.width))
        for _ in range(4):
            f.address(ctx.rng.randrange(1 << k.n))
            f.shift([ctx.rng.randrange(2) for _ in range(8)], sample=True)
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def l1_gsr_after_reconfig(ctx: GenContext, k: LutKind) -> Gen:
    """Reload, then pulse GSR, with and without shifting under it. UG953 names no GSR
    effect on CFGLUT5: the model infers the loaded function is kept (no claim, S44)."""
    for name, shift_under_gsr in (("keep", False), ("shift", True)):
        init = ctx.rng.getrandbits(k.width)
        f = _cfglut(ctx, k, name, init)
        f.load(init ^ ones(k))
        f.sweep()
        f.b.glbl("GSR", 1)
        f.b.sample()
        if shift_under_gsr:
            f.shift([1, 0, 1], sample=True)
            f.b.set(CE=0)
        f.b.glbl("GSR", 0)
        f.sweep()
        yield f.build()


def l2_random(ctx: GenContext, k: LutKind) -> Gen:
    """Seeded random mixes of reloads (CE 0/1, random CDI) and reads, both clock senses."""
    rng = ctx.rng
    for i in range(RANDOM_CONFIGS):
        inv = i % 2
        f = _cfglut(ctx, k, f"r{i}_clk{inv}", rng.getrandbits(k.width), IS_CLK_INVERTED=BIN[inv])
        f.sweep()
        for _ in range(RANDOM_STEPS):
            if rng.random() < RELOAD_P:
                f.shift([rng.randrange(2)], ce=int(rng.random() < CE_HIGH_P), sample=True)
            else:
                f.read(rng.randrange(1 << k.n))
        f.b.set(CE=0)
        f.sweep()
        yield f.build()


def generators(prim: str) -> dict[str, Callable[[GenContext], Gen]]:
    """test.yaml function name -> generator, for vectors/gen.py of each primitive."""
    k = KINDS[prim]
    table = {
        "l0_smoke": l0_smoke,
        "l0_illegal_init": l0_illegal_init,
        "l1_default_init": l1_default_init,
        "l1_projections": l1_projections,
        "l2_init_sweep": l2_init_sweep,
    }
    if k.width > 4:
        table["l2_init_random"] = l2_init_random
    if k.reconfig:
        table |= {
            "l1_edge_polarity": l1_edge_polarity,
            "l1_ce_low_holds": l1_ce_low_holds,
            "l1_reconfigure": l1_reconfigure,
            "l1_cdo_cascade": l1_cdo_cascade,
            "l1_partial_shift": l1_partial_shift,
            "l1_is_clk_inverted": l1_is_clk_inverted,
            "l1_shift_while_reading": l1_shift_while_reading,
            "l1_gsr_after_reconfig": l1_gsr_after_reconfig,
            "l2_random": l2_random,
        }
    else:
        table["l1_gsr_transparent"] = l1_gsr_transparent
    if prim == "LUT6_2":
        table |= {"l1_o5_lower_half": l1_o5_lower_half, "l1_doc_example": l1_doc_example}
    return {name: partial(fn, k=k) for name, fn in table.items()}
