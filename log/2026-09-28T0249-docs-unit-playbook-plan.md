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
- `xut lint --branch` (4G scope): 0 issues.

## Follow-up: PR #12 review round (ruling S53)

Both reviews asked for changes: code quality raised M1–M4 and 12 nits; correctness raised M1–M5 and 7 nits. Every item is addressed.

- **Q-M1: shared code moves into infra.** P1 now adds `xut.unitkit`, holding:
  - the standard reasons, `runners`, `entry`, `class_bins` and the YAML dumper;
  - the README skeleton;
  - `vector_reach`, which uses the python runner's own `generate` and the new `replay_config`;
  - the parametrised `UnitGuards`.

  Units import it and never copy it or the flops code. The flops migration is a TODO in P1.
- **Q-M2:** every shared file uses the stem `luts`. The plan explains why a stem must be unique: pytest's flat namespace.
- **Q-M3:** B2 has its own `git add`, which includes `luts_recipes.py`.
- **Q-M4:** the bins guard uses `xut.lint.gap_bin`, through `unitkit`.
- **C-M1:** the CFGLUT5 model tracks `known`, the order-free uniform value, and never reads it off the contents computed under the inferred order. Both counterexamples are now tests.
- **C-M2:** `L1.edge_polarity` is a pure configuration for C1–C7 and both `IS_CLK_INVERTED` bins. The guard `test_every_exercised_bin_has_a_pure_configuration` pins it. `ones_to_zero` replaces `rand_to_zero`. The plan's coverage statements are corrected.
- **C-M3:** a probe applies the inactive edge alone with CE High. Tests show the both-edges mutant and the ignores-IS_CLK_INVERTED mutant fail documented bits.
- **C-M4:** there is one host-wide lock, `flock "$XDG_RUNTIME_DIR/xut-heavy.lock"`, on every heavy command. It is in Global Constraints and in P1's AGENTS.md §10.1 amendment.
- **C-M5:** A8 has a row for site-constrained primitives (`unitkit.HW_PAD`), and Appendix W rows 8, 13 and 15–17 and 20–21 reference it.
- **Nits.** All are fixed:
  - generated wrappers are rendered and covered by the drift guard;
  - magic numbers are named;
  - `_cfglut`, a shared `lit`, and the dead `ATTR_PAGE` and `page` parameter removed;
  - CFGLUT5 `clock_edge` guards, and the GSR test renamed;
  - the LUT grouping statements are not claims;
  - an S52 note on `init_sweep`, a final sweep in `cdo_cascade`, and the C5 lower bound as a gap;
  - pytest budgets after step 3, and a missing model source is `n/a`.
- **P1 also** drops the TEMPORARY `pre_s19` and `REGENERATED_ON_BRANCH` allowances in `test_status_schema.py`.

### Scratch setup redo

While setting up the scratch copy of `main`, I once ran `git add -A` with its output sent to `/dev/null`. That broke the rule. I re-ran the add and the commit with their output logged; both logs are empty, with no errors. I then compared `git ls-tree -r` of the scratch base commit with `origin/main`. They are identical blob for blob, apart from the submodule gitlink, which `git archive` never includes and no check uses. So no verification depended on a failed add.

### Test results

The code was run on a scratch copy of `main` with P1 applied, in 4G or 16G scopes. The heavy runs waited on the new lock while another agent's job held it.
- luts shared tests: 145 passed.
- The full non-container suite, including the luts tests: 1840 passed, 1 failed. The failure was `test_every_status_stub_matches_its_catalog_entry_and_work_unit`, because the luts stubs were stale. After `xut status init --refresh-bins`, which refreshed exactly the 8 luts stubs as Task A1 Step 5 expects, that test passes.
- P1 tests: `test_unitkit`, `test_golden_reach` and the new runner test all pass.
- sv testbenches: every documented check passes on Icarus against UNISIM 2025.2, in a 1G-capped container.
- The cocotb stand-in run passed.
- ruff is clean on tools, models and tests.

## Follow-up: PR #12 correctness re-review M6 (ruling S55)

The re-review confirmed M1–M5 and raised M6: CFGLUT5 credited claims on events that a model breaking the rule would pass unchanged. Ruling S55 is applied.

- **Credit only on deciding events.** CFGLUT5 now credits:
  - C3 (and C7 when inverted) only on the edge that sets `known` to a new value;
  - C4 only on a CE-Low edge whose CDI differs from `known`;
  - C5 only after a 32-shift run that flipped `known`.
- **Stimulus changes.** `L0.smoke` no longer exercises C3. `L1.edge_polarity` drives the opposite CDI before its CE-Low edge.
- **Model tests.** Four new tests: a same-value shift credits no C3/C7; a CE-Low edge with CDI equal to the contents credits no C4; 32 same-value shifts credit no C5; the flip credits C3 and C5. The 32-equal-shifts-from-non-uniform test now asserts no C5.
- **P1 (`xut.unitkit`).** New `mutant_fails` and `Unit.mutants` (`{claim: mutant_model_factory}`). `UnitGuards` gains `test_every_credited_claim_has_a_failing_mutant`: every claim a vector test exercises must have a mutant, and that mutant must fail a documented bit in some crediting configuration. Two new kit tests cover it.
- **luts mutants.**
  - LUTn: C1 reads the neighbouring address; C2 is the all-ones default.
  - LUT6_2: C1 on O6; C2/C4 read O5 from the upper 32 bits; C3 is the all-ones default.
  - CFGLUT5: O6/O5 stuck; never shifts; ignores CE; CDO stuck at INIT[31]; ignores INIT; ignores `IS_CLK_INVERTED`.
  - A unit check adds a second bit-order mutant (reversed INIT order) for every LUTn and LUT6_2.
- **Part A and the appendix.** A2 and A3 state the rule and the guard in general form. Review Focus 1–2 and D20 record it.

Verification, on the scratch copy of `main` plus P1 and luts:
- luts pytest in a 4G scope: `164 passed`;
- the cocotb stand-in in a 4G scope: exit 0;
- ruff format and check: clean;
- the non-container suite under the heavy lock in a 16G scope: `1862 passed, 5 skipped` (1698 with P1 alone).

Next: re-review of PR #12.
