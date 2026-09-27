# SPDX-License-Identifier: Apache-2.0
"""Single source of the luts unit's generated files: each primitive's test.yaml,
README.md, vectors/gen.py, cocotb module and (LUT1-LUT6, LUT6_2) sv wrappers.

    uv run python tests/7series/clb/_shared/luts/luts_tests.py [PRIM ...]

The shared pieces come from ``xut.unitkit`` (ruling S53). test_luts_tests.py fails when a
committed file differs from this rendering. The stem ``luts`` is the unit's name, so it is
unique across units: pytest's default import mode puts every ``_shared/<unit>`` module in
one flat namespace, where two units' ``recipes.py`` would collide.
"""

from __future__ import annotations

import functools
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from luts_recipes import BIN, KINDS, RANDOM_INITS, LutKind, generators, lit, ones, projection

from xut import unitkit
from xut.unitkit import CO_HW, CO_PY, CO_XS, HW_GSR, HW_REJ, SV_HW, SV_PY, VL_REJ, X_VL, Reason
from xut_models.base import Out

if TYPE_CHECKING:
    from xut.catalog.model import CatalogEntry

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
FAMILY = "7series"
GROUP_DIR = ROOT / "tests" / FAMILY / "clb"
GENERATOR = "tests/7series/clb/_shared/luts/luts_tests.py"
#: prim -> (first page, last page) of its UG953 v2026.1 section
PAGES = {
    "LUT1": (488, 489),
    "LUT2": (491, 492),
    "LUT3": (494, 495),
    "LUT4": (497, 499),
    "LUT5": (500, 502),
    "LUT6": (504, 507),
    "LUT6_2": (509, 512),
    "CFGLUT5": (348, 349),
}
TITLE = {
    **{f"LUT{n}": f"{n}-input look-up table" for n in range(1, 7)},
    "LUT6_2": "6-input, 2-output look-up table",
    "CFGLUT5": "5-input look-up table, reconfigurable at run time",
}
CFG_VL: Reason = (
    "unsupported",
    "status/PORTABILITY.md: verilatorize cannot transform CFGLUT5 (a forced reg's trigger "
    "cone crosses a non-blocking-written reg, ruling S28); no Verilator result until the "
    "srl/CFGLUT5 recovery of ruling S29(2)",
)
NO_X = "no x/z on any input (sv_x_inputs covers x)"
NO_TIMING = "propagation delay is not measured (timing is out of scope, spec §2)"
#: Ruling S52: a CFGLUT5 read whose value depends on the inferred bit order credits nothing
S52 = (
    "claims: reads that depend on CFGLUT5's inferred bit order are exercised but credit "
    "nothing (ruling S52; findings/CFGLUT5-doc-gap-L1-projections.md)"
)
#: tests whose twin (LUT6/LUT6_2, LUT5/CFGLUT5) has a test of the same name
SHARED_WITH_TWIN = (
    "smoke",
    "illegal_init",
    "default_init",
    "projections",
    "init_sweep",
    "init_random",
    "sv_x_inputs",
    "sv_gsr_midsim",
    "cocotb_random",
)
TWIN = {"LUT6": "LUT6_2", "LUT6_2": "LUT6", "LUT5": "CFGLUT5", "CFGLUT5": "LUT5"}


@functools.cache
def _entry(prim: str) -> CatalogEntry:
    from xut.catalog.model import load_entry

    return load_entry(FAMILY, prim, ROOT)


def _bins(prim: str, port: str, *events: str) -> list[str]:
    return unitkit.class_bins(_entry(prim), port, *events)


def _inputs(k: LutKind) -> list[str]:
    return [b for i in range(k.n) for b in _bins(k.prim, f"I{i}")]


def _outs(k: LutKind) -> list[str]:
    return [f"port:{o}" for o in k.outputs]


def _claims(k: LutKind, *ns: int) -> list[str]:
    return unitkit.claims(k.prim, *ns)


def _runners(k: LutKind, **over: Reason) -> unitkit.Declared:
    """CFGLUT5 is never run on Verilator (CFG_VL)."""
    return unitkit.runners(**({**over, "verilator": CFG_VL} if k.reconfig else over))


def _sampling(k: LutKind) -> dict[str, list]:
    if k.width <= 4:
        return {"INIT": [f"every {k.width}-bit value ({1 << k.width})"]}
    return {
        "INIT": ["all zeros", "all ones", f"walking ones x{k.width}", f"walking zeros x{k.width}"]
    }


def _cocotb_configs(k: LutKind) -> list[dict]:
    rng = random.Random(f"{FAMILY}.{k.prim}.L2.cocotb_random")
    cfgs = [{"cfg": "default", "attrs": {}}, {"cfg": "ones", "attrs": {"INIT": lit(k, ones(k))}}]
    for i in range(2):
        attrs = {"INIT": lit(k, rng.getrandbits(k.width))}
        if k.reconfig:
            attrs["IS_CLK_INVERTED"] = BIN[i]
        cfgs.append({"cfg": f"rand{i}", "attrs": attrs})
    return cfgs


Add = Callable[..., None]


def tests_for(k: LutKind) -> list[tuple[dict, str]]:
    prim, out = k.prim, []

    def add(
        level: str,
        name: str,
        style: str,
        source: str,
        exercises: Sequence[str],
        why: str,
        *,
        gaps: Sequence[str],
        related: Sequence[str] = (),
        **kw: object,
    ) -> None:
        twin = [f"{FAMILY}.{TWIN[prim]}.{level}.{name}"] if prim in TWIN else []
        rel = [*(twin if name in SHARED_WITH_TWIN else []), *related]
        kw.setdefault("declared", _runners(k))
        e = unitkit.entry(
            FAMILY, prim, level, name, style, source, exercises, gaps=gaps, related=rel, **kw
        )
        out.append((e, why))

    # C1 (LUT6_2/CFGLUT5: C1, C2) is credited by an explicit INIT's reads; the default's
    # claim by INIT unset. CFGLUT5 reads of an arbitrary INIT credit nothing (ruling S52).
    table = _claims(k, 1, 2) if len(k.outputs) > 1 else _claims(k, 1)
    default = _claims(k, {"LUT6_2": 3, "CFGLUT5": 6}.get(prim, 2))
    ordered = [] if k.reconfig else table
    s52 = [S52] if k.reconfig else []
    shift_bins = (
        [*_bins(prim, "CDI"), *_bins(prim, "CE"), *_bins(prim, "CLK")] if k.reconfig else []
    )
    clk_attrs = [f"attr:IS_CLK_INVERTED={v}" for v in BIN] if k.reconfig else []
    base = [*_outs(k), *_inputs(k)]
    add(
        "L0",
        "smoke",
        "vector",
        "vectors/gen.py:l0_smoke",
        [*base, "attr:INIT", *table, *default, *shift_bins, *clk_attrs],
        "Elaborates with the default INIT and two sampled ones and reads every address: the "
        "minimum any toolchain must get right. The default configuration sets no attribute, "
        "so the model's documented default meets the simulators' own.",
        sampling={
            "INIT": ["unset (default)", "all ones", "1 seeded random"],
            **({"IS_CLK_INVERTED": [0, 1]} if k.reconfig else {}),
        },
        gaps=[
            "one sweep per configuration",
            NO_X,
            "illegal values are tried only by L0.illegal_init",
            *s52,
        ],
        related=[f"{FAMILY}.{prim}.L0.illegal_init"],
    )
    add(
        "L0",
        "illegal_init",
        "vector",
        "vectors/gen.py:l0_illegal_init",
        [],
        f"An INIT with x digits is not the HEX value UG953 asks for (p{PAGES[prim][1]}); the "
        "simulation must reject it (expect=reject), the runtime-rejection path of spec §4.1.",
        declared=_runners(k, verilator=VL_REJ, hw=HW_REJ),
        gaps=[
            "only an all-x INIT is tried; an over-wide literal is refused by xut wrap",
            "whether UNISIM rejects it is observed, not documented (Task A6 rule)",
        ],
        related=[f"{FAMILY}.{prim}.L0.smoke"],
    )
    add(
        "L1",
        "default_init",
        "vector",
        "vectors/gen.py:l1_default_init",
        [*base, *default, *(table if k.reconfig else [])],
        "INIT unset: every address reads 0 (a ground, per the Introduction); a flow that "
        "drops or mangles the default fails here.",
        gaps=["the default is the only value; explicit zero is in L2.init_sweep", NO_X],
    )
    add(
        "L1",
        "projections",
        "vector",
        "vectors/gen.py:l1_projections",
        [*base, "attr:INIT", *ordered],
        "INIT chosen so the output equals one input (and its complement), for every input: "
        "pins the input-to-address order of the logic table; a swapped pair fails at once.",
        sampling={"INIT": [f"projection of I<j> and its complement, j = 0..{k.n - 1}"]},
        gaps=["single-input functions only; general INITs are in L2", NO_X, *s52],
    )
    if k.reconfig:
        _cfglut5_tests(k, add, base, shift_bins)
    else:
        add(
            "L1",
            "gsr_transparent",
            "vector",
            "vectors/gen.py:l1_gsr_transparent",
            [*base, "attr:INIT", *table],
            "Inputs move while GSR is asserted. UG953 names no GSR effect on a LUT, so the "
            "model infers the table holds (inferred:, no claim, ruling S44): a disagreement "
            "is a doc-gap finding, never masked.",
            declared=_runners(k, hw=HW_GSR),
            gaps=[
                "claims are credited only by the sweeps before and after the pulse",
                "one GSR pulse, one configuration",
            ],
            related=[f"{FAMILY}.{prim}.L1.sv_gsr_midsim"],
        )
    if prim == "LUT6_2":
        add(
            "L1",
            "o5_lower_half",
            "vector",
            "vectors/gen.py:l1_o5_lower_half",
            [*base, "attr:INIT", *_claims(k, 1, 2)],
            "Each I4..I0 is read with I5 low then high: O5 must not move (lower 32 bits "
            "only) while O6 switches to the upper half.",
            sampling={
                "INIT": [
                    "lower: I0 projection, upper: its complement",
                    "lower zero, upper ones",
                    "1 seeded random",
                ]
            },
            gaps=[NO_X],
        )
        add(
            "L1",
            "doc_example",
            "vector",
            "vectors/gen.py:l1_doc_example",
            [*base, "attr:INIT", *_claims(k, 1, 2, 4)],
            "UG953's own example (p509): 64'hFFFFFFFFFFFFFFFE is a 6-input OR on O6 and a "
            "5-input OR on O5.",
            sampling={"INIT": ["64'hFFFFFFFFFFFFFFFE"]},
            gaps=["one INIT", NO_X],
        )
    add(
        "L2",
        "init_sweep",
        "vector",
        "vectors/gen.py:l2_init_sweep",
        [*base, "attr:INIT", *table],
        "Spec §4.2 INIT sampling ("
        + ("every value" if k.width <= 4 else "boundaries, walking ones and zeros")
        + "), each read at every address: every INIT bit is seen alone, set and clear.",
        sampling=_sampling(k),
        gaps=[
            "the addresses are visited in binary order (L2.init_random adds random order)",
            NO_X,
            NO_TIMING,
            *s52,
        ],
        related=[f"{FAMILY}.{prim}.L1.projections"],
    )
    if k.width > 4:
        add(
            "L2",
            "init_random",
            "vector",
            "vectors/gen.py:l2_init_random",
            [*base, "attr:INIT", *ordered],
            "Seeded random INITs, each swept and then read at random addresses, where "
            "several inputs change at once.",
            sampling={"INIT": [f"{RANDOM_INITS} seeded random (the test's seed)"]},
            gaps=[
                "one seed per run; a failing seed is frozen by hand (xut freeze-seed is deferred)",
                NO_X,
                *s52,
            ],
            related=[f"{FAMILY}.{prim}.L2.cocotb_random"],
        )
    _sim_tests(k, add, table, default, ordered, clk_attrs)
    return out


def _sim_tests(
    k: LutKind,
    add: Add,
    table: list[str],
    default: list[str],
    ordered: list[str],
    clk_attrs: list[str],
) -> None:
    """The sv and cocotb tests (simulation only)."""
    prim = k.prim
    sv = f"sv/tb_{prim.lower()}"
    ports = [f"port:{p['name']}" for p in _entry(prim).ports]
    rand = lit(k, random.Random(prim).getrandbits(k.width))
    cfgs = (
        [{"cfg": "ones", "attrs": {"INIT": lit(k, ones(k))}}]
        if k.reconfig
        else [
            {"cfg": "rand", "attrs": {"INIT": rand}},
            {"cfg": "p0", "attrs": {"INIT": lit(k, projection(k, 0))}},
        ]
    )
    add(
        "L1",
        "sv_x_inputs",
        "sv",
        f"{sv}_x.sv",
        # CFGLUT5: only the uniform (order-free) checks decide a claim (ruling S52)
        [*ports, "attr:INIT", *(_claims(k, 1, 2, 4) if k.reconfig else table)],
        "Documented reads are checked (an all-ones function; CE Low holds). x on I, CDI "
        "and CE is recorded as checkpoints, compared between simulators."
        if k.reconfig
        else "Every defined address is checked against the logic table; x on each input, "
        "where the two INIT bits it selects agree and where they differ, is recorded as "
        "checkpoints: UG953 does not define x behaviour, so crosscheck compares simulators.",
        declared=_runners(k, python=SV_PY, verilator=X_VL, hw=SV_HW),
        flows=["rtl"],
        gaps=["x behaviour is undocumented: checkpoints only, never checks", "no z inputs"],
        configs=cfgs,
    )
    add(
        "L1",
        "sv_gsr_midsim",
        "sv",
        f"{sv}_gsr.sv",
        [*ports, "attr:INIT", *(_claims(k, 1, 2, 3, 5, 6) if k.reconfig else table)],
        "32 zero shifts replace the whole function whatever the shift order; GSR is then "
        "pulsed, its effect recorded as checkpoints, and 32 one shifts are checked."
        if k.reconfig
        else "The logic table is checked before and after a GSR pulse; the output while GSR "
        "is asserted is a checkpoint (UG953 names no GSR effect on a LUT).",
        declared=_runners(k, python=SV_PY, hw=SV_HW),
        flows=["rtl"],
        gaps=["the GSR effect is undocumented: checkpoints only", "one configuration"],
        configs=cfgs[:1],
        related=[f"{FAMILY}.{prim}.L1.{'gsr_after_reconfig' if k.reconfig else 'gsr_transparent'}"],
    )
    co = _cocotb_configs(k)
    add(
        "L2",
        "cocotb_random",
        "cocotb",
        f"cocotb/cocotb_{prim.lower()}_random.py",
        [*ports, "attr:INIT", *ordered, *default, *clk_attrs],
        "Long model-checked random sessions on Icarus"
        + ("" if k.reconfig else " and Verilator")
        + "; a failing seed is frozen into a vector test that also runs on xsim and hardware.",
        declared=_runners(k, python=CO_PY, xsim=CO_XS, hw=CO_HW),
        flows=["rtl"],
        gaps=["no GSR mid-session", f"{len(co)} configurations", NO_X],
        configs=co,
    )


def _cfglut5_tests(k: LutKind, add: Add, base: list[str], shift_bins: list[str]) -> None:
    prim, rel = k.prim, [f"{FAMILY}.{k.prim}.L1.reconfigure"]
    clk_attrs = [f"attr:IS_CLK_INVERTED={v}" for v in BIN]
    add(
        "L1",
        "edge_polarity",
        "vector",
        "vectors/gen.py:l1_edge_polarity",
        [*base, *shift_bins, "attr:INIT", *clk_attrs, *_claims(k, 1, 2, 3, 4, 5, 6, 7)],
        "The pure CFGLUT5 test: every sample is order-independent (uniform contents). The "
        "inactive edge with CE High must change nothing, for both IS_CLK_INVERTED values "
        "(a both-edges or wrong-edge simulator fails a documented bit); 32 shifts of the "
        "opposite value then flip the whole function. It credits every claim whatever the "
        "inferred bit order turns out to be.",
        sampling={"INIT": ["all zeros", "all ones"], "IS_CLK_INVERTED": [0, 1]},
        gaps=["only uniform contents: the bit order is left to the other tests", NO_X],
        related=rel,
    )
    add(
        "L1",
        "ce_low_holds",
        "vector",
        "vectors/gen.py:l1_ce_low_holds",
        [*base, *_bins(prim, "CDI"), *_bins(prim, "CLK"), "attr:INIT", *_claims(k, 1, 2, 4)],
        "CE Low with CDI toggling and CLK running: the function and CDO do not move.",
        gaps=[
            "CE is never raised here (see reconfigure)",
            "only the all-ones configuration "
            "credits C4; the others' reads depend on the inferred order (ruling S52)",
            NO_X,
        ],
        related=rel,
    )
    add(
        "L1",
        "reconfigure",
        "vector",
        "vectors/gen.py:l1_reconfigure",
        [*base, *shift_bins, "attr:INIT", *_claims(k, 1, 2, 3, 5)],
        "A new 32-bit function is shifted in through CDI and read back at every address.",
        gaps=[
            "the read-back order relies on the inferred shift direction (a disagreement is "
            "a doc-gap); only ones_to_zero credits C3 and C5 (ruling S52)",
            NO_X,
        ],
    )
    add(
        "L1",
        "cdo_cascade",
        "vector",
        "vectors/gen.py:l1_cdo_cascade",
        ["port:CDO", *shift_bins, "attr:INIT", *_claims(k, 3, 5)],
        "64 shifts with CDO sampled after each: the old INIT leaves on CDO, then the first "
        "shifted-in bits arrive 32 shifts later, as a CDO-to-CDI chain needs.",
        gaps=[
            "which INIT bit reaches CDO first is inferred; only ones_zeros_ones credits "
            "(ruling S52)",
            "documented bits bound the chain length only from above: a chain shorter than "
            "32 bits shows only on inferred bits; the two-LUT chain is an L3 design",
            NO_X,
        ],
        related=rel,
    )
    add(
        "L1",
        "partial_shift",
        "vector",
        "vectors/gen.py:l1_partial_shift",
        [*base, *shift_bins, "attr:INIT"],
        "1, 5, 16 and 31 shifts leave a mix of old and new bits: pins the shift order.",
        gaps=[
            "the order is inferred; a disagreement is a doc-gap "
            "(findings/CFGLUT5-doc-gap-L1-partial_shift.md)",
            S52,
            NO_X,
        ],
        related=rel,
    )
    add(
        "L1",
        "is_clk_inverted",
        "vector",
        "vectors/gen.py:l1_is_clk_inverted",
        [
            *base,
            *_bins(prim, "CDI", "1"),
            *_bins(prim, "CE"),
            *_bins(prim, "CLK"),
            "attr:INIT",
            "attr:IS_CLK_INVERTED=1'b1",
            *_claims(k, 3),
        ],
        "IS_CLK_INVERTED=1: samples after each rise show no shift, after each fall one.",
        sampling={"IS_CLK_INVERTED": [1], "INIT": ["all zeros", "all ones"]},
        gaps=[
            "the intermediate samples depend on the inferred order; L1.edge_polarity is "
            "the order-free test of the same claim",
            "claim:CFGLUT5.C7 is exercised, not credited: a simulator that shifts on the "
            "rise differs here only on samples that depend on the inferred shift order "
            "(ruling S52); L1.edge_polarity credits it",
            NO_X,
        ],
        related=[f"{FAMILY}.{prim}.L1.edge_polarity"],
    )
    add(
        "L1",
        "shift_while_reading",
        "vector",
        "vectors/gen.py:l1_shift_while_reading",
        [*base, *shift_bins, "attr:INIT"],
        "An address is held while bits shift in, so the function changes while in use.",
        gaps=[S52, NO_X],
        related=rel,
    )
    add(
        "L1",
        "gsr_after_reconfig",
        "vector",
        "vectors/gen.py:l1_gsr_after_reconfig",
        [*base, *shift_bins, "attr:INIT"],
        "GSR after a reload, with and without shifts under it. UG953 names no GSR effect "
        "on CFGLUT5: the model infers the function is kept (inferred:, no claim, S44).",
        declared=_runners(k, hw=HW_GSR),
        gaps=["the GSR outcome is inferred; a disagreement is a doc-gap, never masked"],
        related=[f"{FAMILY}.{prim}.L1.sv_gsr_midsim"],
    )
    add(
        "L2",
        "random",
        "vector",
        "vectors/gen.py:l2_random",
        [*base, *shift_bins, "attr:INIT", *clk_attrs],
        "Seeded random mixes of reloads (CE 0/1, random CDI) and reads, both clock senses.",
        sampling={"INIT": ["8 seeded random"], "IS_CLK_INVERTED": [0, 1]},
        gaps=["one seed per run", "no GSR (L1.gsr_after_reconfig)", S52, NO_X],
        related=[f"{FAMILY}.{prim}.L2.cocotb_random"],
    )


# --- rendering -------------------------------------------------------------------------


def render_test_yaml(k: LutKind) -> str:
    doc = {
        "primitive": k.prim,
        "family": FAMILY,
        "work_unit": "luts",
        "doc_refs": [
            {"guide": "UG953", "version": "2026.1", "section": k.prim, "page": PAGES[k.prim][0]}
        ],
        "tests": [e for e, _ in tests_for(k)],
    }
    return unitkit.dump_test_yaml(doc, GENERATOR)


def render_readme(k: LutKind) -> str:
    first, last = PAGES[k.prim]
    overview = (
        f"{k.prim} reads a {k.width}-bit INIT at the address formed by its inputs; "
        + (
            "CE-enabled CLK edges shift a new INIT in through CDI, and CDO cascades it. "
            if k.reconfig
            else "it has no clock and no state. "
        )
        + f"Behavioural claims are in `catalog/7series/{k.prim}.overrides.yaml`."
    )
    oracle = [
        f"Vector tests: the clean-room golden model `models/xut_models/7series/"
        f"{k.prim.lower()}.py` (shared logic in `_common/luts.py`), written from UG953 alone. "
        "Every expected bit carries `doc:<page>` or `inferred:<reason>`.",
        "sv tests: self-checks of documented behaviour only; x and GSR cases are "
        "checkpoints compared between simulators by `xut crosscheck`.",
        "cocotb: the same golden model, step by step.",
        "References: UNISIM on xsim, Icarus"
        + (
            " (Verilator: see runner support)."
            if k.reconfig
            else " and Verilator (the model is unchanged by `xut verilatorize`)."
        ),
    ]
    return unitkit.render_readme(
        prim=k.prim,
        title=TITLE[k.prim],
        reference=f"UG953 v2026.1, section {k.prim}, pages {first}–{last} (CLB / LUT). Work "
        "unit: `luts`. GENERATED by `_shared/luts/luts_tests.py`.",
        overview=overview,
        tests=tests_for(k),
        oracle=oracle,
        known_gaps=[f"{NO_TIMING}."],
        root=ROOT,
    )


def _gen_py(prim: str) -> str:
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        f'"""{prim} vector generators (test.yaml: source: vectors/gen.py:<name>).\n\n'
        'The recipes live in tests/7series/clb/_shared/luts/luts_recipes.py.\n"""\n\n'
        "import luts_recipes\n\n"
        f'globals().update(luts_recipes.generators("{prim}"))\n'
    )


def _cocotb_py(prim: str) -> str:
    p = prim.lower()
    return (
        "# SPDX-License-Identifier: Apache-2.0\n"
        f'"""{FAMILY}.{prim}.L2.cocotb_random: random {prim} session vs the golden model."""\n\n'
        "import cocotb\n"
        "from luts_cocotb import random_session\n\n\n"
        "@cocotb.test()\n"
        f"async def {p}_random(dut: object) -> None:\n"
        f'    await random_session(dut, "{prim}", steps=2000)\n'
    )


def _sv_wrapper(k: LutKind, kind: str) -> str:
    """A LUT1-LUT6/LUT6_2 sv test: defines, then the shared body (CFGLUT5's own sv tests
    are written by hand: its ports differ)."""
    body = {"x": "sv_x_inputs", "gsr": "sv_gsr_midsim"}[kind]
    ins = ", ".join(f".I{i}(I[{i}])" for i in range(k.n))
    outs = ".O6(O), .O5(O5)" if len(k.outputs) > 1 else ".O(O)"
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        f"// {FAMILY}.{k.prim}.L1.{body} (body: _shared/luts/luts_{kind}_tb.svh)",
        f"`define LUT_TB tb_{k.prim.lower()}_{kind}",
        f"`define LUT_N {k.n}",
        *(["`define LUT_DUAL"] if len(k.outputs) > 1 else []),
        f"`define LUT_INST {k.prim} #(.INIT(INIT)) dut ({outs}, {ins});",
        f'`include "luts_{kind}_tb.svh"',
        "",
    ]
    return "\n".join(lines)


def render(prim: str) -> dict[str, str]:
    """Every generated file of ``prim``, by its path relative to the primitive's directory."""
    k = KINDS[prim]
    files = {
        "test.yaml": render_test_yaml(k),
        "README.md": render_readme(k),
        "vectors/gen.py": _gen_py(prim),
        f"cocotb/cocotb_{prim.lower()}_random.py": _cocotb_py(prim),
    }
    if not k.reconfig:
        files |= {f"sv/tb_{prim.lower()}_{kind}.sv": _sv_wrapper(k, kind) for kind in ("x", "gsr")}
    return files


# --- mutants (rulings S55, S55a) -----------------------------------------------------------
# Every mutant factory of the unit lives here. ``mutants(prim)`` gives one per credited
# claim, breaking exactly that claim's rule; the unit's guard asserts each fails a
# documented bit in a configuration that credits the claim (in every one for an event
# claim). The unit's own checks use the others (a second bit order, both edges).


def address_flipped(base: type) -> type:
    """Logic table read at the neighbouring address: the input order is wrong (C1)."""

    class AddressFlipped(base):
        def _address(self, n: int) -> int:
            return super()._address(n) ^ 1

    return AddressFlipped


def init_reversed(base: type) -> type:
    """INIT read end to end, bit 2^n - 1 - a for address a: the other bit order (C1)."""

    class InitReversed(base):
        def _address(self, n: int) -> int:
            return super()._address(n) ^ ((1 << n) - 1)

    return InitReversed


def example_misread(base: type) -> type:
    """LUT6_2 with the p509 example INIT reads it as ...FFFC: every other INIT is read
    right, so only C4 (the example's OR functions) breaks."""

    class ExampleMisread(base):
        def __init__(self, attrs: dict) -> None:
            super().__init__(attrs)
            if self.init == self.OR_EXAMPLE:
                self.init &= ~0b10

    return ExampleMisread


def default_ones(base: type) -> type:
    """An unset INIT reads as all ones, not the documented zero (the default claim)."""

    class DefaultOnes(base):
        def __init__(self, attrs: dict) -> None:
            super().__init__(attrs)
            if not self.explicit_init:
                self.init = (1 << (1 << self.N)) - 1

    return DefaultOnes


def output_replaced(port: str, value: Callable[[object], int]) -> Callable[[type], type]:
    """``port`` shows ``value(model)`` instead of the documented bit."""

    def factory(base: type) -> type:
        class Replaced(base):
            def outputs(self) -> dict:
                out = super().outputs()
                return {**out, port: Out(str(value(self)), out[port].prov)}

        Replaced.__name__ = f"{port}Replaced"
        return Replaced

    return factory


def clock_edge_with_ce(ce: int) -> Callable[[type], type]:
    """CE forced to ``ce`` on every edge (0: never shifts; 1: ignores CE)."""
    if ce not in (0, 1):
        raise ValueError(f"CE must be 0 or 1, not {ce!r}")

    def factory(base: type) -> type:
        class ForcedCe(base):
            def clock_edge(self, port: str, rising: bool) -> None:
                kept = self.pin["CE"]
                self.pin["CE"] = ce
                super().clock_edge(port, rising)
                self.pin["CE"] = kept

        return ForcedCe

    return factory


def init_ignored(base: type) -> type:
    """The start-up contents are all zeros whatever INIT says (C6)."""

    class InitIgnored(base):
        def power_on(self) -> None:
            super().power_on()
            self.contents = 0

    return InitIgnored


def inversion_ignored(base: type) -> type:
    """IS_CLK_INVERTED has no effect: the rising edge is always active (C7)."""

    class InversionIgnored(base):
        def __init__(self, attrs: dict) -> None:
            super().__init__(attrs)
            self.inv_clk = 0

    return InversionIgnored


def both_edges(base: type) -> type:
    """CLK shifts on every edge, the inactive one as well."""

    class BothEdges(base):
        def clock_edge(self, port: str, rising: bool) -> None:
            super().clock_edge(port, not bool(self.inv_clk))

    return BothEdges


def mutants(prim: str) -> dict[str, unitkit.Mutant]:
    """{claim id: its Mutant} for ``prim``: every claim a vector test credits. CFGLUT5's
    C3, C4, C5 and C7 are event claims (a shift, a hold, a cascade, an edge): every
    configuration that credits one must catch its mutant (ruling S55a)."""
    M = unitkit.Mutant
    if prim == "CFGLUT5":
        return {
            "CFGLUT5.C1": M(output_replaced("O6", lambda m: 0)),  # O6 ignores the contents
            "CFGLUT5.C2": M(output_replaced("O5", lambda m: 0)),  # O5 ignores the contents
            "CFGLUT5.C3": M(clock_edge_with_ce(0), event=True),  # never shifts
            "CFGLUT5.C4": M(clock_edge_with_ce(1), event=True),  # ignores CE
            # CDO stuck at the power-on value
            "CFGLUT5.C5": M(
                output_replaced("CDO", lambda m: (m.init >> (m.WIDTH - 1)) & 1), event=True
            ),
            "CFGLUT5.C6": M(init_ignored),
            "CFGLUT5.C7": M(inversion_ignored, event=True),
        }
    if prim == "LUT6_2":
        upper = output_replaced("O5", lambda m: (m.init >> (32 + m._address(5))) & 1)
        return {
            "LUT6_2.C1": M(output_replaced("O6", lambda m: (m.init >> (m._address(6) ^ 1)) & 1)),
            "LUT6_2.C2": M(upper),  # O5 reads the upper 32 bits
            "LUT6_2.C3": M(default_ones),
            "LUT6_2.C4": M(example_misread),  # only the p509 example INIT is misread
        }
    return {f"{prim}.C1": M(address_flipped), f"{prim}.C2": M(default_ones)}


UNIT = unitkit.Unit(
    name="luts",
    family=FAMILY,
    root=ROOT,
    group_dir=GROUP_DIR,
    prims=tuple(KINDS),
    render=render,
    generators=generators,
    mutants=mutants,
)


def main(prims: list[str]) -> None:
    for prim in prims or list(KINDS):
        d = GROUP_DIR / prim
        files = render(prim)
        for rel, text in files.items():
            path = d / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        print(f"wrote {len(files)} files under {d.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
