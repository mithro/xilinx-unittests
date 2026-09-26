# Task 26: FDCE and FDPE golden models, vector, sv and cocotb tests

Branch `unit/7series/flops`, base `06f5a64`. Commits: `aaa6503` (models),
`27fcef2` (tests), plus this log. Rulings applied: S30, S40, S41 (and R1 from the
Task 20 re-review).

## What changed

- `models/xut_models/7series/fdce.py`, `fdpe.py`: clean-room from UG953 v2026.1
  only; no UNISIM source was opened. Each constant was checked against the UG953 text:
  - FDCE: the Introduction and logic table are on p369 ("When CLR is active, it
    overrides all other inputs and resets the data output (Q) Low"; logic-table row
    CLR=1, CE=X, D=X, C=X gives Q=0). The attribute table is on p370, with the INIT
    default `1'b0`. So `CTRL=CLR`, `CTRL_VALUE=0`, `CTRL_ASYNC=True`,
    `INIT_DEFAULT=0`, `PAGE=369`, `ATTR_PAGE=370`.
  - FDPE: p372 ("When PRE is asserted, it overrides all other inputs and presets the
    data output (Q) High"; logic-table row PRE=1 gives Q=1) and p373 (INIT default
    `1'b1`). So `CTRL=PRE`, `CTRL_VALUE=1`, `CTRL_ASYNC=True`, `INIT_DEFAULT=1`,
    `PAGE=372`, `ATTR_PAGE=373`.
  - Doc note: on p373/p374 the FDPE VHDL and Verilog instantiation templates show
    `INIT => '0'` / `.INIT(1'b0)`, which contradicts the attribute-table default
    `1'b1`. The model follows the attribute table. The `L1.capture` config
    `default` (no INIT set) passes on iverilog and xsim, so UNISIM's default agrees
    with the table.
- `_common/flops.py`, R1 (S41(3)): under GSR, an active async control now stops an
  edge from re-tagging Q with `_GSR_EDGE`, **whatever CE is**. This deliberately
  deviates from the literal one-line fix in task-20-review.md,
  `self.pin["CE"] or (not self.CTRL_ASYNC and self._ctrl_active())`, which still
  re-tags when CE is High because the `CE` term short-circuits. The logic tables
  (p369/p372) give CE=X, C=X while CLR/PRE is active, so the edge is a don't-care
  whatever CE is. The code is now
  `if not (self.CTRL_ASYNC and ctrl) and (self.pin["CE"] or ctrl)`. FDRE and FDSE are
  unaffected, because for them `CTRL_ASYNC` is False and the expression reduces to the
  old one.
- `test_flop_models.py`:
  - `PRIMS` gains FDCE and FDPE. Before the models existed, all 52 new cases failed
    with `LookupError`.
  - `fresh()` now holds the control at its inactive level, as the vector `Flop` and
    the cocotb session already do. Without that, an inverted async control with its
    pin Low is *active*: the model correctly forces Q at GSR release and hits
    C3/C6, which broke `test_c6_control_active_low` and
    `test_c6_not_hit_from_gsr_edge_probe` for FDCE/FDPE. The tests were right to
    fail, because their setup was not idle. FDRE and FDSE are unaffected, since a
    sync control acts only at an edge.
  - `test_gsr_versus_async_control_inferred_control_wins` now also runs over
    `IS_<ctrl>_INVERTED` 0/1, and asserts the S30 reason text.
  - New `test_edge_under_gsr_with_async_control_keeps_provenance` (R1, over CE 0/1
    and INIT agreeing or disagreeing).
  - New `test_edge_while_async_control_forces_rehits_nothing` (S41(4), over CE 0/1
    and IS_C_INVERTED 0/1).
  - Mutation check (scratchpad `t26/mutate-r1.log`, `t26/mutate-rehit.log`):
    - the original line fails 8 R1 cases;
    - the literal one-liner fails the 4 CE=1 cases;
    - "re-force async on every edge" fails all 8 re-hit cases.
- `test_flop_tests.py`: `EXPECTED_PRESENT` gains FDCE and FDPE.
- `tests/7series/register/{FDCE,FDPE}/`: `vectors/gen.py`, `sv/tb_<prim>_gsr.sv`,
  `sv/tb_<prim>_x.sv` and `cocotb/cocotb_<prim>_random.py` follow the brief. One
  exception: `gen.py` keeps the extra docstring line ("The recipes live in
  ...") that FDRE's and FDSE's `gen.py` have, so the siblings stay identical.
  `test.yaml` and `README.md` were generated with `flop_tests.py FDCE FDPE`. Running
  `flop_tests.py FDRE FDSE` again left FDRE and FDSE **byte-identical** (empty
  `git diff`).
- `status/*.yaml` was not touched. No crosscheck or `status record` was run (S40/S41(2)).

## Test results

- Model tests: 122 passed, 2 skipped. The skips are the sync-only
  `test_c5_control_force_on_inverted_edge` for FDCE/FDPE.
- `pytest tests/7series/register/_shared/flops/`: 140 passed, 2 skipped.
  `test_exercises_are_reach_confirmed` passes for FDRE, FDSE, FDCE and FDPE.
- Step 4, async stimulus: `xut run --runner python` passes every vector test (26
  pass, 6 declared skips). `xut vec check` on the `clear_async`/`preset_async`/
  `*_recovery` stimuli (cfg-init0/init1) reports no errors and `hw_renderable: yes`.
  An independent scan of all 140 FDCE/FDPE `stim.xvec` files
  (`t26/async_spacing.py`) found 1209 async-control sets, 0 of them sharing their time
  with another event, and a minimum distance to an edge of 1000 ps (= `async_sep_ps`).
- S41(4) on real vectors (`t26/rehit_probe.py`): every FDCE/FDPE vector was replayed
  through an instrumented model. Edges taken while an async control already forces Q
  numbered 3726 for FDCE and 4760 for FDPE; they made **0 claim hits and 0 Q changes**.
  No real vector takes an edge while GSR is high and the control is active, so R1 is
  pinned only by the model unit test.
- `xut run '7series.FDCE.*' '7series.FDPE.*' --runner python --runner iverilog
  --runner xsim --jobs 40` took 368 s and gave 96 results. Counted from the log's
  table, and matching its 96 progress lines:

  | prim | runner | pass | skip | fail | error |
  |---|---|---|---|---|---|
  | FDCE | python | 13 | 3 | 0 | 0 |
  | FDCE | iverilog | 15 | 0 | 1 | 0 |
  | FDCE | xsim | 14 | 1 | 1 | 0 |
  | FDPE | python | 13 | 3 | 0 | 0 |
  | FDPE | iverilog | 15 | 0 | 1 | 0 |
  | FDPE | xsim | 14 | 1 | 1 | 0 |

  - Skips are all declared: sv tests on python, cocotb on python and xsim.
  - The only failures are `L0.illegal_init` on iverilog and xsim for both primitives:
    "init_x: expected rejection, got acceptance: the run reached XUT_DONE (INIT)".
    This is the same failure already known from FDRE/FDSE, and it is left for Task 24.
  - Every vector test (13 per primitive, including `*_async`/`*_recovery`) passes on
    iverilog and xsim against the golden model.
  - cocotb on iverilog: 4 configs, 0 mismatches each.
  - The sv traces (`sv_gsr_midsim`, `sv_x_inputs`, both primitives) are identical
    between iverilog and xsim apart from the header's `runner=` field.
- `uv run xut lint`: 0 errors and 0 warnings. The 56 related-id warnings from Task 25
  are gone.
- `uv run xut lint --branch`: 0 errors and 0 warnings, both before and after the tests
  commit.
- ruff: the model and `gen.py` files pass clean. Test files show only the known ANN
  gap. `ruff format --check` passes clean.
- Fast suite (`pytest -q -n 16 -m "not slow" tools/tests tests`): 1416 passed,
  2 skipped.

## For Task 24: the S30 inference disagrees with both simulators

No committed test holds GSR high while CLR/PRE is active, so the vector runs never
compare the S30 inference. A scratch-only probe (`t26/gsrprobe/`, not committed)
simulated stock UNISIM 2025.2 on iverilog (xut-sim:1) and on xsim, applying the same
sequence to FDCE and FDPE with INIT 0 and 1:

- (A) assert GSR, then the control, then edges, then release GSR, then release the
  control;
- (B) assert the control, then GSR, then release the control, then release GSR.

iverilog and xsim agree with each other at every point: **GSR wins**. FDCE with
INIT=1 and FDPE with INIT=0 show INIT while GSR is high, even with the control active.
The model (S30) gives the control value there, tagged `inferred:`. The disagreement
falls exactly on the model's `inferred:` points (A.gsr+ctrl, the two edges under
GSR, and B.ctrl+gsr), and every `doc:` point agrees. Logs: `t26/gsrprobe/
{iverilog,xsim,model}.log`. Under S30/S41(1) this is the anticipated `doc-gap`. It is
reported here and was not masked: the model and tests are unchanged. Because the
R1 fix keeps the S30 reason on Q through those edges, a finding would cite the right
inference.

Task 24 needs a stimulus that reaches this case, for example an async recipe that
asserts the control while GSR is high. Otherwise crosscheck will never see it.

## Next steps

- Task 24 (after the PR C merge and rebase): run Verilator and iverilog-vz, then
  crosscheck and `status record` for all four flops.
  - Classify `L0.illegal_init`.
  - Decide how to put the GSR-vs-control case into a committed test, and file the
    doc-gap.
  - Consider the FDPE template-vs-table INIT inconsistency as a doc note.
