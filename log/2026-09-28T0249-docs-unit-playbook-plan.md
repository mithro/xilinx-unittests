# docs/unit-playbook: the unit fan-out playbook plan (luts first)

Branch `docs/unit-playbook`, from `main` at 73a775f.

## What changed

- Added `docs/superpowers/plans/2026-09-28-unit-playbook.md`:
  - **Part 0**: Task P1, an infra prerequisite found while writing the plan. `attr:<A>` for a
    non-enumerated attribute (every LUT INIT, BRAM `INIT_xx`, DSP/MMCM integers) was never
    in `bins_reached`, so no vector test could cover it. `xut.golden.coverage_reach` names
    bins as `coverage_bins` does. P1 also extends the ruff ANN exemption to
    `tests/**/test_*.py`, which was the flops unit's open TODO.
  - **Part A**: the generic unit procedure, Tasks A1–A8:
    - intake, overrides and claims;
    - clean-room models;
    - recipes, the metadata generator and the reach guard;
    - sv tests;
    - the cocotb session;
    - the full run, crosscheck, findings by class, and status;
    - the PR gate;
    - the hardware follow-up.
    Every heavy command runs in a capped scope: `xut run --jobs 16` in 32G, and whole-suite
    `pytest -n 4` in 32G.
  - **Part B**: the luts unit (LUT1–LUT6, LUT6_2, CFGLUT5), Tasks B1–B8, with complete code:
    - the overrides and claims;
    - the golden models;
    - the recipes: exhaustive truth tables, spec §4.2 INIT sampling, and CFGLUT5 reload
      sequences;
    - the test.yaml/README generator and its guards;
    - the sv testbenches and the cocotb session.
    In total there are 87 tests and 700 vector configurations.
  - **Appendix W**: the fan-out order and a row for each of the 27 units: portability,
    hardware class and infra blockers (P2 `smoke_attrs`, P3 clock observers, P4 DRP, P5 the
    pad harness, P6 real-time rendering, and the S29(2) recovery).
  - **Decisions D1–D16** on spec gaps. D4 (claim credit when a documented rule has an
    inferred detail) and D16 (a unit refreshes its own status stubs) need the orchestrator
    to confirm them.

## Test results (planning only; no heavy runs)

The Part B code was checked in a scratch copy of the repository layout against PR #10's
infra (`infra-verilatorize`), with the P1 change applied to a scratch copy of `tools/xut`.
All Python ran in 4G-capped scopes.
- Models, recipes and generators: all 700 vector configurations validate and replay.
- `pytest` over the luts shared directory: 125 passed. That is 83 model tests and 42 guards:
  drift, schema, reach through `coverage_reach`, and bins accounted.
- P1's test: 3 passed.
- The cocotb session ran against a stand-in `XutDut` for every primitive.
- The sv testbenches were compiled and run on Icarus against Vivado 2025.2 UNISIM, in a
  1G-capped container. Every documented check passes. Only pass/fail was read, never an
  undocumented checkpoint's value, so the clean-room rule holds.
  - This found a time-0 testbench race: with a declaration initialiser, LUT6's output stayed
    x at the first check. The fix, a time-0 non-blocking update, is now a Part A rule
    (decision D7).
- ruff check and format: clean on every extracted module (P1's ANN exemption applied to the
  test files).
- The plan was not run end to end: this branch runs no `xut run`.

## Next steps

- Review this PR (two reviewers).
- The orchestrator rules on D4 and D16.
- After PR #10 merges: implement P1 (`infra/unit-prereqs`), then the luts unit (Part B).

## Follow-up: orchestrator rulings on PR #12

- **Ruling S52 overrides D4.** It follows S44: a CFGLUT5 output whose value depends on the
  inferred bit order credits no claim. This applies to O6/O5 indexing, the shift direction
  and the CDO bit, even though the reconfiguration rule itself is documented. The plan now
  does the following:
  - The model credits every CFGLUT5 claim only while the contents are uniform (all 0 or
    all 1, `doc:348`) and do not depend on the GSR inference. C6 is credited at power-on
    for a uniform INIT, which includes the all-zeroes default.
  - The recipes add order-independent cases: all ones in `L1.ce_low_holds` (C4),
    `rand_to_zero` in `L1.reconfigure` (C3, C5), and `ones_zeros_ones` in
    `L1.cdo_cascade` (C3, C5). Every claim C1–C7 keeps a crediting test, so none moved to
    `gaps`.
  - The generator declares no claims for the order-dependent tests: `L1.projections`,
    `L1.partial_shift`, `L1.shift_while_reading`, `L1.gsr_after_reconfig`,
    `L2.init_random`, `L2.random`, and the cocotb session apart from C6. Each of these tests
    notes S52 in its `gaps`.
  - The sv tests' claims are limited to their uniform checks.
  - Task B1 writes two `doc-gap` stubs up front, `findings/CFGLUT5-doc-gap-L1-projections.md`
    (the O5/O6 tables) and `findings/CFGLUT5-doc-gap-L1-partial_shift.md` (the shift
    direction and the CDO bit). Task B6 records in them the order UNISIM shows.
  - Part A's claim rules state S52 in general form.
  - Vector configurations: 702 (CFGLUT5 124).
- **D16 is confirmed.** Task P1 now also amends AGENTS.md §7, which is infra-owned, to let a
  unit branch refresh its own never-recorded stubs. The flops unit's 115f0cc is covered.
- D1–D3 and D5–D15 were accepted.

### Test results

These ran in the scratch layout, in 4G scopes:
- `pytest` on the luts shared directory: 128 passed (86 model tests, 42 guards; the reach
  guard covers all 702 configurations).
- The cocotb stand-in run passed.
- ruff: clean on the Python blocks extracted from the plan.
- `xut lint --branch`: see below.
