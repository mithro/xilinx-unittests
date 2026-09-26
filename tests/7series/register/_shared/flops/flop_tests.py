# SPDX-License-Identifier: Apache-2.0
"""Single source of the flops unit's test.yaml and README.md files.

    uv run python tests/7series/register/_shared/flops/flop_tests.py FDRE [FDSE ...]

test_flop_tests.py fails when a committed file differs from this rendering.

Ruling S33: the catalog carries port x class bins (ruling S19) on top of the bare
``port:<P>`` and ``claim:<PRIM>.Cn`` bins the brief's ``_ports``/``_claims`` already
emit. ``_class_bins`` reads them from the catalog's own ``xut.status.port_class_bins``
(never hand-rolled), and each test's exercises names only the ones its recipe actually
drives -- verified against ``xut run --runner python``'s per-test ``bins_reached``
(spec §9, ruling S23): a class bin belongs to a test only when that test's own named
ports include the port, and only when replay actually reaches that specific value/edge
for it (see the per-add() comments below).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from flop_recipes import BIN, KINDS, FlopKind, attr_names

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
PAGES = {"FDRE": (375, 376), "FDSE": (378, 379), "FDCE": (369, 370), "FDPE": (372, 373)}
TITLE = {
    "FDRE": "D flip-flop with clock enable and synchronous reset",
    "FDSE": "D flip-flop with clock enable and synchronous set",
    "FDCE": "D flip-flop with clock enable and asynchronous clear",
    "FDPE": "D flip-flop with clock enable and asynchronous preset",
}
ALL_FLOWS = ["rtl", "vivado", "yosys", "openxc7", "vpr"]
RUNNERS = ("python", "xsim", "iverilog", "verilator", "hw")
# (value, reason) pairs; values are the step-1 schema strings "no" | "unsupported".
HW_GSR = ("unsupported", "GSR pulses need the GSR-immune harness state of spec §7.2")
SV_PY = ("no", "self-checking sv testbench; there is no golden-model replay")
SV_HW = ("unsupported", "sv testbenches are simulation-only (spec §4.3)")
X_VL = (
    "unsupported",
    "2-state simulator: x stimulus is randomised per X seed (spec §5.6), so "
    "the undocumented x checkpoints cannot be compared",
)
CO_XS = ("unsupported", "cocotb has no xsim backend (spec §4.3)")
CO_HW = ("unsupported", "cocotb runs in simulation; failing seeds are frozen into vector tests")
CO_PY = ("no", "the cocotb test compares against the golden model itself")
VL_REJ = ("unsupported", "a 2-state simulator cannot represent the 1'bx attribute value")
HW_REJ = ("unsupported", "rejection of an illegal attribute is a simulation-model check")


def hw_inv_d(ap: int) -> tuple[str, str]:
    return (
        "unsupported",
        f"UG953 p{ap}: IS_D_INVERTED must be 0 unless the flop is an I/O "
        "register; the fabric harness uses SLICE flops",
    )


def _runners(**over: tuple[str, str]) -> tuple[dict, dict]:
    """(runners, unsupported_reasons) in the step-1 schema's string form."""
    runners = {r: over[r][0] if r in over else "yes" for r in RUNNERS}
    return runners, {r: reason for r, (_, reason) in over.items()}


def _claims(k: FlopKind, *ns: int) -> list[str]:
    return [f"claim:{k.prim}.C{n}" for n in ns]


def _ports(k: FlopKind, *names: str) -> list[str]:
    return [f"port:{n}" for n in names]


def _attrs(names) -> list[str]:
    return [f"attr:{n}={v}" for n in names for v in BIN]


_ENTRIES: dict[str, object] = {}


def _entry(prim: str):
    """The primitive's catalog entry, cached (ruling S33: bin names come from here,
    never hand-rolled)."""
    if prim not in _ENTRIES:
        from xut.catalog.model import load_entry

        _ENTRIES[prim] = load_entry("7series", prim, ROOT)
    return _ENTRIES[prim]


def _class_bins(prim: str, port: str) -> dict[str, str]:
    """``event -> bin`` for one catalog port, from ``xut.status.port_class_bins``
    (ruling S19/S33): ``{"0": "port:D:0", "1": "port:D:1"}`` for a data port,
    ``{"edge": "port:C:edge"}`` for a clock."""
    from xut.status import port_class_bins

    p = next(p for p in _entry(prim).ports if p["name"] == port)
    return {b.rsplit(":", 1)[1]: b for b in port_class_bins(p)}


def _reach(k: FlopKind, port: str, *events: str) -> list[str]:
    """The `events` bins of `port` (e.g. ``_reach(k, "D", "0", "1")``), reach-confirmed
    against ``xut run --runner python``'s per-test ``bins_reached`` (ruling S23): only
    the values/edges a test's own recipe is checked to actually drive are named here."""
    bins = _class_bins(k.prim, port)
    return [bins[e] for e in events]


def _reach_all(k: FlopKind, port: str) -> list[str]:
    """Every class bin of `port`, in the catalog's own order: ``["port:C:edge"]`` for
    the clock, ``["port:R:0", "port:R:1"]`` for a ``data`` control (FDRE/FDSE), or
    ``["port:CLR:assert", "port:CLR:release"]`` for an ``async`` one with a declared
    ``active`` level (FDCE/FDPE, ruling S19) -- so, unlike ``_reach``, no event name
    needs to be spelled out per kind. This is only correct where a test's own recipe
    is checked to actually drive *both* events of `port`: a `Flop.__init__`-only touch
    (the control's initial, inactive value) is not enough -- see ruling S33's I1/M2:
    smoke never calls `.ctrl()`, so it must not use this helper for the control."""
    return list(_class_bins(k.prim, port).values())


def _related(k: FlopKind, level: str, suffix: str) -> list[str]:
    out = []
    for o in KINDS.values():
        if o is k or (("_async" in suffix or "_recovery" in suffix) and not o.is_async):
            continue
        s = suffix.replace(k.word, o.word).replace(f"is_{k.ctrl.lower()}_", f"is_{o.ctrl.lower()}_")
        out.append(f"7series.{o.prim}.{level}.{s}")
    return out


def tests_for(k: FlopKind) -> list[tuple[dict, str]]:
    p, ap = PAGES[k.prim]
    c, w, lc = k.ctrl, k.word, k.ctrl.lower()
    all_ports = _ports(k, "C", "CE", "D", "Q", c)
    out: list[tuple[dict, str]] = []

    def add(
        level,
        suffix,
        style,
        source,
        exercises,
        why,
        *,
        gaps,
        sampling=None,
        runners=None,
        flows=None,
        configs=None,
        exclusions=None,
        related=(),
    ):
        assert gaps, f"{suffix}: every test must say what it misses"
        declared, reasons = runners or _runners()
        e = {
            "id": f"7series.{k.prim}.{level}.{suffix}",
            "level": level,
            "style": style,
            "source": source,
            "exercises": exercises,
            "attr_sampling": sampling or {},
            "runners": declared,
            "flows": flows or ALL_FLOWS,
            "related": _related(k, level, suffix) + list(related),
            "gaps": list(gaps),
        }
        if reasons:
            e["unsupported_reasons"] = reasons
        if exclusions:
            e["config_exclusions"] = exclusions
        if configs:
            e["configs"] = configs
        out.append((e, why))

    init_s = {"INIT": [0, 1]}
    no_x = "no x/z on any input (sv_x_inputs covers x)"
    d1 = {
        "hw": {
            "*_d1_*": f"IS_D_INVERTED=1 (UG953 p{ap}) is only legal on I/O registers; "
            "the fabric harness uses SLICE flops"
        }
    }
    # Ruling S33 (I1/M2): l0_smoke sweeps all 16 attribute combinations, so both D:1/CE:1
    # occur (D:0 never occurs: 1-INIT XOR IS_D_INVERTED only ever differs from the
    # builder's own 0 default when it lands on 1) -- verified against `xut run --runner
    # python`'s bins_reached for 7series.FDRE.L0.smoke. smoke never calls `.ctrl()`
    # (its own gaps say so), so no control class bin is named here: `Flop.__init__`'s
    # initial, inactive control value is not an intending test, and for an async
    # control (FDCE/FDPE) the "assert" bin is not even reachable that way (only
    # "release", from the inverted case's 0->1 init line) -- reset_over_ce,
    # is_{ctrl}_inverted and the L2 tests are what intend R/CLR/S/PRE's class bins.
    add(
        "L0",
        "smoke",
        "vector",
        "vectors/gen.py:l0_smoke",
        all_ports
        + _reach_all(k, "C")
        + _reach(k, "CE", "1")
        + _reach(k, "D", "1")
        + _attrs(attr_names(k))
        + _claims(k, 1, 4),
        "Every one of the 16 attribute combinations elaborates, powers up to INIT and "
        "captures once on every simulator: the minimum any toolchain must get right.",
        sampling={n: [0, 1] for n in attr_names(k)},
        exclusions=d1,
        gaps=[
            "only one capture per configuration; no control, CE-low or GSR activity",
            no_x,
            "illegal values are tried only by L0.illegal_init",
        ],
        related=[f"7series.{k.prim}.L0.illegal_init"],
    )
    add(
        "L0",
        "illegal_init",
        "vector",
        "vectors/gen.py:l0_illegal_init",
        [],
        f"INIT=1'bx is outside UG953's 1'b0/1'b1 (p{ap}); the simulation must reject it "
        "(expect=reject), which exercises the runtime-rejection path of spec §4.1.",
        # python stays "yes": it prepares dut/, stim.xvec, an empty expected.xtr and
        # configs.json for every vector test, reject tests included (Task 8 "Reject tests").
        runners=_runners(verilator=VL_REJ, hw=HW_REJ),
        gaps=[
            "only INIT=1'bx is tried; over-width literals are truncated at elaboration "
            "and IS_*_INVERTED illegal values are not tried",
            "whether UNISIM rejects it is observed, not documented (see Task 24)",
        ],
        related=[f"7series.{k.prim}.L0.smoke"],
    )
    # Ruling S33: l1_capture drives C:edge, CE:1, D:0 and D:1 (verified bins_reached);
    # it never touches the control, so no R bin is named here.
    add(
        "L1",
        "capture",
        "vector",
        "vectors/gen.py:l1_capture",
        _ports(k, "C", "CE", "D", "Q")
        + _reach_all(k, "C")
        + _reach(k, "CE", "1")
        + _reach(k, "D", "0", "1")
        + _claims(k, 1),
        "Pins the basic D-to-Q transfer on the active edge, for both INIT values and for "
        "the all-defaults configuration (model defaults vs UNISIM defaults).",
        sampling=init_s,
        gaps=[
            "CE held High and the control inactive throughout",
            "no GSR after power-up",
            "default polarities only",
            no_x,
        ],
        related=[f"7series.{k.prim}.L2.exhaustive"],
    )
    add(
        "L1",
        "ce_hold",
        "vector",
        "vectors/gen.py:l1_ce_hold",
        _ports(k, "C", "CE", "D", "Q")
        + _reach_all(k, "C")
        + _reach(k, "CE", "0", "1")
        + _reach(k, "D", "0", "1")
        + _claims(k, 2),
        "Shows that CE Low makes clock edges no-ops even with D different from Q.",
        sampling=init_s,
        gaps=[
            "CE never toggles within a cycle (between edges only)",
            "control inactive",
            "default polarities only",
            no_x,
        ],
    )
    add(
        "L1",
        f"{w}_over_ce",
        "vector",
        f"vectors/gen.py:l1_{w}_over_ce",
        _ports(k, c, "CE", "Q") + _reach(k, "CE", "0", "1") + _reach_all(k, c) + _claims(k, 3),
        (
            f"{c} must win over CE Low and over D, "
            + ("at once, with no clock edge." if k.is_async else "at the next active edge.")
            + " A priority inversion here is a classic synthesis-mapping bug."
        ),
        sampling=init_s,
        gaps=[
            f"{c} is never asserted and released within one clock period"
            if not k.is_async
            else f"{c} release timing relative to the clock is covered only by {w}_recovery",
            "default polarities only",
            no_x,
        ],
    )
    if k.is_async:
        # Ruling S33 (I1): both call `.ctrl(True)` and `.ctrl(False)` for real (unlike
        # smoke, which only ever sets the control's initial, inactive value), so both
        # assert/release class bins are genuinely reached here.
        add(
            "L1",
            f"{w}_async",
            "vector",
            f"vectors/gen.py:l1_{w}_async",
            _ports(k, c, "Q") + _reach_all(k, c) + _claims(k, 3),
            f"{c} acts without any clock edge, repeatedly, from both Q values.",
            sampling=init_s,
            gaps=[
                "no clock activity while the control is asserted",
                "no GSR overlap",
                "default polarities only",
            ],
        )
        add(
            "L1",
            f"{w}_recovery",
            "vector",
            f"vectors/gen.py:l1_{w}_recovery",
            _ports(k, c, "C", "D", "Q") + _reach_all(k, c) + _claims(k, 1, 3),
            f"After {c} is released, the next active edge captures D. The edge is at least "
            "async_sep_ps after the release, so recovery timing is not tested (spec §2).",
            sampling=init_s,
            gaps=[
                "recovery/removal timing is out of scope (spec §2)",
                "one release per configuration",
            ],
        )
    add(
        "L1",
        "gsr_init",
        "vector",
        "vectors/gen.py:l1_gsr_init",
        _ports(k, "Q") + _claims(k, 4),
        "A GSR pulse mid-run returns Q to INIT from the opposite value; checks glbl handling "
        "in every simulator and, later, every flow's INIT mapping.",
        sampling=init_s,
        runners=_runners(hw=HW_GSR),
        gaps=[
            "GSR overlapping an active control is not driven here",
            "edges during GSR are an inferred behaviour (see sv_gsr_midsim)",
        ],
        related=[f"7series.{k.prim}.L1.sv_gsr_midsim"],
    )
    add(
        "L1",
        "is_c_inverted",
        "vector",
        "vectors/gen.py:l1_is_c_inverted",
        _ports(k, "C", "Q") + _reach_all(k, "C") + ["attr:IS_C_INVERTED=1'b1"] + _claims(k, 5),
        "Samples after both edges show capture only on the falling edge.",
        sampling={"INIT": [0, 1], "IS_C_INVERTED": [1]},
        gaps=[
            "CE High and control inactive throughout; the other inversions stay 0 "
            "(combinations are in L2.exhaustive)"
        ],
    )
    add(
        "L1",
        f"is_{lc}_inverted",
        "vector",
        f"vectors/gen.py:l1_is_{lc}_inverted",
        _ports(k, c, "Q") + _reach_all(k, c) + [f"attr:IS_{c}_INVERTED=1'b1"] + _claims(k, 6),
        f"{c} held Low acts as active; a flow that drops the inversion fails at once.",
        sampling={"INIT": [0, 1], f"IS_{c}_INVERTED": [1]},
        gaps=["one assertion per configuration; other inversions stay 0"],
    )
    add(
        "L1",
        "is_d_inverted",
        "vector",
        "vectors/gen.py:l1_is_d_inverted",
        _ports(k, "D", "Q")
        + _reach(k, "D", "0", "1")
        + ["attr:IS_D_INVERTED=1'b1"]
        + _claims(k, 7),
        "Q takes the complement of D.",
        sampling={"INIT": [0, 1], "IS_D_INVERTED": [1]},
        runners=_runners(hw=hw_inv_d(ap)),
        gaps=[
            f"claim:{k.prim}.C8 — IS_D_INVERTED=1 is only legal on I/O registers; a "
            "placement rule for hardware flows (steps 3-4), not a simulation behaviour"
        ],
    )
    add(
        "L2",
        "exhaustive",
        "vector",
        "vectors/gen.py:l2_exhaustive",
        all_ports
        + _reach_all(k, "C")
        + _reach(k, "CE", "0", "1")
        + _reach(k, "D", "0", "1")
        + _reach_all(k, c)
        + _attrs(attr_names(k))
        + _claims(k, 1, 2, 3, 5, 6, 7),
        "Every attribute combination x prior Q x (control, CE, D): the complete "
        "single-edge truth table.",
        sampling={n: [0, 1] for n in attr_names(k)},
        exclusions=d1,
        gaps=[
            "single edge per combination: no multi-cycle ordering (see L2.random)",
            "no GSR (L1.gsr_init and sv_gsr_midsim cover it; hardware GSR needs §7.2)",
            no_x,
        ],
        related=[f"7series.{k.prim}.L1.capture"],
    )
    add(
        "L2",
        "random",
        "vector",
        "vectors/gen.py:l2_random",
        all_ports
        + _reach_all(k, "C")
        + _reach(k, "CE", "0", "1")
        + _reach(k, "D", "0", "1")
        + _reach_all(k, c)
        + _attrs(attr_names(k))
        + _claims(k, 1, 2, 3),
        "Seeded constrained-random sequences find ordering effects that the "
        "single-edge table cannot.",
        sampling={n: [0, 1] for n in attr_names(k)},
        exclusions=d1,
        gaps=[
            "no GSR (hardware GSR needs §7.2; L1.gsr_init covers simulation)",
            "one seed per run; failing seeds must be frozen by hand (xut freeze-seed is deferred)",
            no_x,
        ]
        + (["the control only changes between edges (sync kinds)"] if not k.is_async else []),
        related=[f"7series.{k.prim}.L2.cocotb_random"],
    )
    add(
        "L1",
        "sv_gsr_midsim",
        "sv",
        f"sv/tb_{k.prim.lower()}_gsr.sv",
        _ports(k, "Q") + _claims(k, 4),
        "Direct UNISIM instances for both INIT values; glbl GSR is forced mid-run while "
        "clocking. Edges during GSR are recorded, not judged, because UG953 is silent.",
        runners=_runners(python=SV_PY, hw=SV_HW),
        flows=["rtl"],
        gaps=[
            "behaviour of clock edges while GSR is active: undocumented, checkpoint only",
            "default IS_* polarities only",
            "control inactive throughout",
        ],
        configs=[{"cfg": "default", "attrs": {}}],
        related=[f"7series.{k.prim}.L1.gsr_init"],
    )
    add(
        "L1",
        "sv_x_inputs",
        "sv",
        f"sv/tb_{k.prim.lower()}_x.sv",
        _ports(k, "CE", "D", c, "Q") + _claims(k, 2, 3),
        "X on D, CE or the control: the documented cases (CE Low holds; the control "
        "overrides) are checked; the undocumented ones are recorded for cross-simulator "
        "comparison. Not run on Verilator: see unsupported_reasons (plan ambiguity 9).",
        runners=_runners(python=SV_PY, verilator=X_VL, hw=SV_HW),
        flows=["rtl"],
        gaps=[
            "UG953 does not define X behaviour; X on D with CE High, X on CE and X on the "
            "control are checkpoints only",
            "no x on C",
            "default polarities only",
        ],
        configs=[{"cfg": "default", "attrs": {}}],
    )
    add(
        "L2",
        "cocotb_random",
        "cocotb",
        f"cocotb/cocotb_{k.prim.lower()}_random.py",
        all_ports + _claims(k, 1, 2, 3, 4),
        "Long model-checked random sessions on Icarus and Verilator; any failing seed becomes "
        "a frozen vector test that also runs on xsim and hardware.",
        runners=_runners(python=CO_PY, xsim=CO_XS, hw=CO_HW),
        flows=["rtl"],
        gaps=["no GSR mid-session", "only 4 of the 16 attribute configurations", no_x],
        configs=[
            {"cfg": "default", "attrs": {}},
            {"cfg": "init1", "attrs": {"INIT": "1'b1"}},
            {
                "cfg": "inv_all",
                "attrs": {
                    "IS_C_INVERTED": "1'b1",
                    "IS_D_INVERTED": "1'b1",
                    f"IS_{c}_INVERTED": "1'b1",
                },
            },
            {"cfg": "init1_inv_c", "attrs": {"INIT": "1'b1", "IS_C_INVERTED": "1'b1"}},
        ],
        related=[f"7series.{k.prim}.L2.random"],
    )
    return out


HEADER = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    "# GENERATED by tests/7series/register/_shared/flops/flop_tests.py; edit that file.\n"
)


class _NoAliasDumper(yaml.SafeDumper):
    """M4: the shared `ALL_FLOWS`/`init_s`/`d1` objects would otherwise dump as YAML
    anchors and aliases (`flows: &id001`, `*id001`, ...): fragile for a reader of one
    test's entry, and for any consumer that mutates one test's list in place. Every
    test's fields are written out in full instead."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def render_test_yaml(k: FlopKind) -> str:
    p, _ = PAGES[k.prim]
    doc = {
        "primitive": k.prim,
        "family": "7series",
        "work_unit": "flops",
        "doc_refs": [{"guide": "UG953", "version": "2026.1", "section": k.prim, "page": p}],
        "tests": [e for e, _ in tests_for(k)],
    }
    # safe_dump quotes the strings "yes"/"no" ('yes'), so they reload as strings, as the
    # step-1 schema requires; test_flop_tests.py validates the output against that schema.
    return HEADER + yaml.dump(
        doc, Dumper=_NoAliasDumper, sort_keys=False, width=100, allow_unicode=True
    )


def _cell(e: dict, runner: str) -> str:
    v = e["runners"][runner]
    return v if v == "yes" else f"{v}: {e['unsupported_reasons'][runner]}"


def render_readme(k: FlopKind, root: Path = ROOT) -> str:
    p, ap = PAGES[k.prim]
    tests = tests_for(k)
    findings = sorted((root / "findings").glob(f"{k.prim}-*.md"))
    lines = [
        f"# {k.prim} — {TITLE[k.prim]}",
        "",
        f"UG953 v2026.1, section {k.prim}, pages {p}–{ap} (REGISTER / SDR). "
        "Work unit: `flops`. GENERATED by `_shared/flops/flop_tests.py`.",
        "",
        "## Overview",
        "",
        f"{k.prim} is a single D flip-flop with clock enable and "
        + ("an asynchronous " if k.is_async else "a synchronous ")
        + f"{k.word} input `{k.ctrl}` that drives Q {'High' if k.forced else 'Low'}. "
        "GSR loads INIT. Programmable inversion exists on C, D and the control pin. "
        f"Behavioural claims {k.prim}.C1–C8 are in `catalog/7series/{k.prim}.overrides.yaml`.",
        "",
        "## Tests",
        "",
        "| ID | Level | Style | Exercises |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| `{e['id']}` | {e['level']} | {e['style']} | {', '.join(e['exercises'])} |"
        for e, _ in tests
    ]
    lines += ["", "## Why each test is useful, and what it misses", ""]
    for e, why in tests:
        lines.append(f"- `{e['id']}`: {why}")
        lines += [f"  - Misses: {g}" for g in e["gaps"]]
        for runner, excl in e.get("config_exclusions", {}).items():
            lines += [
                f"  - Not on {runner} for configurations `{pat}`: {why_x}"
                for pat, why_x in excl.items()
            ]
    lines += [
        "",
        "## Oracle",
        "",
        f"- Vector tests: the clean-room golden model `models/xut_models/7series/"
        f"{k.prim.lower()}.py` (shared logic in `_common/flops.py`), written from UG953 "
        "alone. Every expected bit carries `doc:<page>` or `inferred:<reason>`, and bits "
        "UG953 leaves undefined are `-`.",
        "- sv tests: self-checks of documented behaviour only; undocumented X and GSR "
        "cases are checkpoints compared between simulators by `xut crosscheck`.",
        "- cocotb: the same golden model, cycle by cycle.",
        "- References: UNISIM on xsim, Icarus and Verilator (after `xut verilatorize`, "
        "guarded by its Icarus equivalence check).",
        "",
        "## Known gaps (all tests)",
        "",
        "- Timing (setup/hold, clock-to-Q, recovery/removal) is out of scope (spec §2).",
    ]
    gaps = dict.fromkeys(g for e, _ in tests for g in e["gaps"])
    lines += [f"- {g}" for g in gaps]
    lines += [
        "",
        "## Runner support and expected divergences",
        "",
        "| Test | python | xsim | iverilog | verilator | hw |",
        "|---|---|---|---|---|---|",
    ]
    for e, _ in tests:
        lines.append(f"| `{e['id']}` | " + " | ".join(_cell(e, x) for x in RUNNERS) + " |")
    lines += ["", "Findings:" if findings else "Findings: none recorded.", ""]
    lines += [f"- [{f.stem}](../../../../findings/{f.name})" for f in findings]
    lines += ["", "## Related tests", ""]
    lines += [f"- `{e['id']}`: " + ", ".join(f"`{r}`" for r in e["related"]) for e, _ in tests]
    lines += [
        "",
        "## How to run",
        "",
        "```bash",
        f"uv run xut run '7series.{k.prim}.*' --jobs 40 > .cache/run-{k.prim.lower()}.log 2>&1",
        f"uv run xut crosscheck '7series.{k.prim}.*' > .cache/xc-{k.prim.lower()}.log 2>&1",
        f"uv run xut status record {k.prim}",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(prims: list[str]) -> None:
    for prim in prims:
        d = ROOT / "tests/7series/register" / prim
        d.mkdir(parents=True, exist_ok=True)
        (d / "test.yaml").write_text(render_test_yaml(KINDS[prim]))
        (d / "README.md").write_text(render_readme(KINDS[prim]))
        print(f"wrote {d}/test.yaml and README.md")


if __name__ == "__main__":
    main(sys.argv[1:])
