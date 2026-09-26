# SPDX-License-Identifier: Apache-2.0
"""Stimulus recipes shared by the flops work unit (FDRE, FDSE, FDCE, FDPE).

Each recipe takes a GenContext and a FlopKind and yields .xvec files built with
VecBuilder, so every file satisfies the spec §5.1 class rules by construction.
Recipes only drive inputs and place samples: expected values come from the
golden model (python runner), never from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from itertools import product

BIN = ("1'b0", "1'b1")


@dataclass(frozen=True)
class FlopKind:
    prim: str
    ctrl: str  # R | S | CLR | PRE
    is_async: bool
    word: str  # reset | set | clear | preset (used in test ids)
    forced: int  # the value the control drives onto Q
    init_default: int


KINDS = {
    "FDRE": FlopKind("FDRE", "R", False, "reset", 0, 0),
    "FDSE": FlopKind("FDSE", "S", False, "set", 1, 1),
    "FDCE": FlopKind("FDCE", "CLR", True, "clear", 0, 0),
    "FDPE": FlopKind("FDPE", "PRE", True, "preset", 1, 1),
}


def inv(port: str) -> str:
    return f"IS_{port}_INVERTED"


def attr_names(k: FlopKind) -> tuple[str, ...]:
    return ("INIT", inv("C"), inv("D"), inv(k.ctrl))


def all_configs(k: FlopKind):
    """All 16 combinations of the four 1-bit attributes: (cfg name, attrs)."""
    for bits in product((0, 1), repeat=4):
        name = f"i{bits[0]}_c{bits[1]}_d{bits[2]}_{k.ctrl.lower()}{bits[3]}"
        yield name, {n: BIN[b] for n, b in zip(attr_names(k), bits, strict=True)}


class Flop:
    """One configuration, driven in logical terms (control active/inactive, logical D)."""

    def __init__(self, ctx, k: FlopKind, cfg: str, attrs: dict[str, str]):
        self.k, self.attrs = k, attrs
        self.b = ctx.dut(cfg, **attrs)
        self.inv_d = int(attrs.get(inv("D"), BIN[0])[-1])
        self.inv_ctrl = int(attrs.get(inv(k.ctrl), BIN[0])[-1])
        self.init = int(attrs.get("INIT", BIN[k.init_default])[-1])
        self.ctrl_on = False
        self.b.init(**{k.ctrl: self.inv_ctrl})  # inactive while glbl holds GSR

    def ctrl(self, active: bool) -> None:
        if active == self.ctrl_on:
            return
        self.ctrl_on = active
        level = int(active) ^ self.inv_ctrl
        if self.k.is_async:
            self.b.async_(self.k.ctrl, level)
        else:
            self.b.set(**{self.k.ctrl: level})

    def data(self, d: int | None = None, ce: int | None = None) -> None:
        ports = {}
        if d is not None:
            ports["D"] = d ^ self.inv_d
        if ce is not None:
            ports["CE"] = ce
        self.b.set(**ports)

    def clock(self, n: int = 1, sample: bool = True) -> None:
        """n full cycles (rise, then fall): one active edge each, whatever IS_C_INVERTED is."""
        self.b.cycle("C", n=n, sample=sample)

    def sample(self) -> str:
        return self.b.sample()

    def load(self, q: int) -> None:
        """Bring Q to q through the documented capture path (C1)."""
        self.ctrl(False)
        self.data(d=q, ce=1)
        self.clock(sample=False)

    def gsr_pulse(self) -> None:
        self.b.glbl("GSR", 1)
        self.b.sample()
        self.b.glbl("GSR", 0)
        self.b.sample()

    def build(self):
        return self.b.build()


def _init_only(ctx, k, init, **extra):
    return Flop(ctx, k, f"init{init}", {"INIT": BIN[init], **extra})


def l0_smoke(ctx, k):
    """16 configurations: power-up value, then one capture of ~INIT."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        f.sample()
        f.data(d=1 - f.init, ce=1)
        f.clock()
        yield f.build()


def l1_capture(ctx, k):
    # "default" sets no attribute at all: the one vector config where the model's
    # documented defaults meet the UNISIM defaults (Review Focus 2).
    for f in [Flop(ctx, k, "default", {})] + [_init_only(ctx, k, init) for init in (0, 1)]:
        for d in (1, 0, 1, 1, 0, 0):
            f.data(d=d, ce=1)
            f.clock()
        yield f.build()


def l1_ce_hold(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.data(d=1 - init, ce=0)
        f.clock(n=3)
        f.data(ce=1)
        f.clock()
        f.data(d=init, ce=0)
        f.clock(n=3)
        yield f.build()


def l1_ctrl_over_ce(ctx, k):
    """The control overrides CE and D: sync at the active edge, async at once."""
    for init, ce in product((0, 1), repeat=2):
        f = Flop(ctx, k, f"init{init}_ce{ce}", {"INIT": BIN[init]})
        f.load(1 - k.forced)
        f.data(d=1 - k.forced, ce=ce)
        f.ctrl(True)
        f.sample()  # async: already forced; sync: unchanged until the edge
        f.clock()  # sync: forced at the active edge
        f.ctrl(False)
        f.sample()  # released: Q keeps the forced value
        f.data(ce=1)
        f.clock()  # captures D again
        yield f.build()


def l1_ctrl_async(ctx, k):
    """Async kinds only: the control acts with no clock edge at all."""
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.load(1 - k.forced)
        for _ in range(3):
            f.ctrl(True)
            f.sample()
            f.ctrl(False)
            f.sample()
            f.load(1 - k.forced)
            f.sample()
        yield f.build()


def l1_recovery(ctx, k):
    """Async kinds only: after release, the next active edge (>= async_sep_ps later) captures D."""
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.ctrl(True)
        f.data(d=1 - k.forced, ce=1)
        f.clock()
        f.ctrl(False)
        f.clock()
        yield f.build()


def l1_gsr(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init)
        f.load(1 - init)
        f.sample()
        f.data(d=1 - init, ce=1)
        f.b.glbl("GSR", 1)
        f.sample()  # INIT (C4)
        f.clock()  # edges while GSR is active (inferred: ignored)
        f.b.glbl("GSR", 0)
        f.sample()
        f.clock()  # captures D again
        yield f.build()


def l1_is_c_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv("C"): BIN[1]})
        for d in (1 - init, init, 1 - init):
            f.data(d=d, ce=1)
            f.clock()  # samples after the rise (no change) and after the fall (capture)
        yield f.build()


def l1_is_ctrl_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv(k.ctrl): BIN[1]})
        f.load(1 - k.forced)
        f.ctrl(True)  # drives the pin Low
        f.sample()
        f.clock()
        f.ctrl(False)
        f.load(1 - k.forced)
        f.sample()
        yield f.build()


def l1_is_d_inverted(ctx, k):
    for init in (0, 1):
        f = _init_only(ctx, k, init, **{inv("D"): BIN[1]})
        for d in (0, 1, 1, 0):
            f.data(d=d, ce=1)  # logical d; Flop.data applies the inversion
            f.clock()
        yield f.build()


def l2_exhaustive(ctx, k):
    """16 configurations x prior Q x (control, CE, D) at an active edge. No GSR, so the
    configurations without IS_D_INVERTED stay hardware-eligible (GSR on hw needs §7.2)."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        for q0, (c, ce, d) in product((0, 1), product((0, 1), repeat=3)):
            f.load(q0)
            f.sample()
            f.data(d=d, ce=ce)
            f.ctrl(bool(c))
            if k.is_async:
                f.sample()
            f.clock()
            f.ctrl(False)
        yield f.build()


def l2_random(ctx, k, steps: int = 300):
    """Seeded constrained-random sessions over the 16 configurations (seed in the header)."""
    for cfg, attrs in all_configs(k):
        f = Flop(ctx, k, cfg, attrs)
        rng = ctx.rng
        for _ in range(steps):
            r = rng.random()
            if k.is_async and r < 0.13:
                f.ctrl(rng.random() < 0.5)
                f.sample()
            else:
                f.data(d=rng.randrange(2), ce=int(rng.random() < 0.8))
                if not k.is_async:
                    f.ctrl(rng.random() < 0.15)
                f.clock()
        yield f.build()


def l0_illegal_init(ctx, k):
    """INIT=1'bx is outside UG953's allowed values: the model must reject it (expect=reject)."""
    b = ctx.dut("init_x", allow_illegal=True, expect="reject", illegal=["INIT"], INIT="1'bx")
    b.sample()
    yield b.build()


def generators(prim: str) -> dict:
    """test.yaml function name -> generator, for vectors/gen.py of each primitive."""
    k = KINDS[prim]
    table = {
        "l0_smoke": l0_smoke,
        "l0_illegal_init": l0_illegal_init,
        "l1_capture": l1_capture,
        "l1_ce_hold": l1_ce_hold,
        f"l1_{k.word}_over_ce": l1_ctrl_over_ce,
        "l1_gsr_init": l1_gsr,
        "l1_is_c_inverted": l1_is_c_inverted,
        f"l1_is_{k.ctrl.lower()}_inverted": l1_is_ctrl_inverted,
        "l1_is_d_inverted": l1_is_d_inverted,
        "l2_exhaustive": l2_exhaustive,
        "l2_random": l2_random,
    }
    if k.is_async:
        table |= {f"l1_{k.word}_async": l1_ctrl_async, f"l1_{k.word}_recovery": l1_recovery}
    return {name: partial(fn, k=k) for name, fn in table.items()}
