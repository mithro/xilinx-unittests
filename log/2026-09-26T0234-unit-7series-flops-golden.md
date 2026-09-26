# flops: clean-room golden model, shared SDR flop + FDRE (Task 20)

Branch `unit/7series/flops`, HEAD before this session 23ec318 (post-rebase onto `main`
a11e51e).

## What changed

- `models/xut_models/7series/_common/flops.py`: `SdrFlop`, the shared clean-room golden
  model for the four SDR flops (FDRE, FDSE, FDCE, FDPE), written from UG953 v2026.1 only
  (FDCE pp. 369-370, FDPE pp. 372-373, FDRE pp. 375-376, FDSE pp. 378-379; no UNISIM
  source was opened). Implements claims C1-C7 (capture, ce_hold, control, gsr_init, inv_c,
  inv_ctrl, inv_d) per `catalog/7series/<PRIM>.overrides.yaml` (Task 19). C8 is a usage
  rule, not simulated behaviour (already noted in the Task 19 log).
- `models/xut_models/7series/fdre.py`: `FDRE(SdrFlop)`, `MODEL = FDRE`. `CTRL="R"`,
  `CTRL_VALUE=0`, `CTRL_ASYNC=False` (synchronous reset), `INIT_DEFAULT=0`, `PAGE=375`,
  `ATTR_PAGE=376`.
- `tests/7series/register/_shared/flops/flop_recipes.py`: the `FlopKind` dataclass and
  `KINDS` table only (`prim`, `ctrl`, `is_async`, `word`, `forced`, `init_default`), copied
  verbatim from the Task 21 Step 1 source so Task 21 can extend the same file without
  touching these lines. FDCE/FDPE/FDSE entries are present in the table (needed so
  `KINDS[prim]` resolves for every primitive), but only FDRE has a model yet.
- `tests/7series/register/_shared/flops/test_flop_models.py`: claim-by-claim tests,
  `PRIMS = ["FDRE"]` (FDSE lands in Task 25, FDCE/FDPE in Task 26).

## Ruling S30 (applied; overrides the brief)

The brief's pseudo-code built `Out("-", "inferred:...")` in two places. A don't-care bit
needs `doc:<page>` provenance (ruling S14, AGENTS.md §8); `Out` refuses a `-` bit tagged
`inferred:`. Per the ruling:

1. `__init__`'s initial state is now `Out(str(self.init), "inferred:...")` (a concrete
   value, not `-`) -- state before power-on is undocumented, so INIT is assumed.
2. `_under_gsr`: when GSR is active, the control is async and active, and
   `INIT != CTRL_VALUE`, the model now returns `Out(str(self.CTRL_VALUE), "inferred:...")`
   and hits the `control` (C3) claim, instead of `Out("-", ...)`. The reasoning: UG953
   states an active CLR/PRE overrides all other inputs (p369/p372) but never names GSR
   in that sentence, so the control is taken to still win. Renamed the constant
   `_GSR_VS_CTRL` to carry this reasoning.
3. Replaced `test_gsr_versus_async_control_is_undefined` with
   `test_gsr_versus_async_control_inferred_control_wins`: the agreeing ("same") case is
   unchanged; the disagreeing case now asserts `bits == str(f)` with `inferred:` provenance,
   and after GSR drops, `bits == str(f)` with `doc:` provenance. `PRIMS = ["FDRE"]` and
   FDRE is not async, so this test's parametrize list is empty for now: pytest collects and
   reports it `SKIPPED`, as the ruling anticipates.
4. `clock_edge`'s GSR-re-tag branch (`_GSR_EDGE`) no longer guards on `self.q.bits != "-"`:
   nothing in the model can produce a `-` bit any more (both prior producers are gone per
   (1) and (2)), so the guard was dead code. Verified by inspection: `_doc`, `_force`, and
   both `_under_gsr` branches only ever build `Out` from a concrete `0`/`1`.

## Deviation: provenance strings cannot contain whitespace

`models/xut_models/base.py`'s `_PROV` regex (`^(doc:\d+|inferred:[^\s#|=,]+)$`) rejects any
whitespace after `inferred:` (confirmed against `tools/tests/test_golden.py`, which asserts
`Out("0", "inferred:has space")` raises). The brief's prose-style reasons
(`"inferred:UG953 describes GSR as holding INIT while active, so clock edges ..."`) would
fail `Out.__post_init__` verbatim. Reworded them as single whitespace-free tokens
(`_`/`-`/`/`/`;` in place of spaces), following the existing convention seen in
`tools/tests/test_xtr.py` (`inferred:doc_silent_on_GSR_vs_CLR`) and the plan
(`inferred:GSR_is_described_as_an_active-state_override...`). No test asserts on the exact
reason text, only the `doc:`/`inferred:` prefix, so this is cosmetic, not a behaviour
change.

## TDD

1. Wrote the tests and `flop_recipes.py` first.
2. Confirmed the predicted failure: with the model files moved aside, `uv run pytest
   tests/7series/register/_shared/flops -v` gave `LookupError: no golden model for
   7series/FDRE` for all 12 non-skipped tests (log kept in `.cache/pytest-fail.log`,
   git-ignored, not committed).
3. Restored the model files (already written) and re-ran: 12 passed, 1 skipped (the async
   test, expected empty until Task 26).

## Verification

- `uv run ruff format` on the four new files: reformatted `test_flop_models.py` (comment
  alignment only, from the brief's own layout); the other three were already formatted.
- `uv run ruff check` on the four new files: clean on the two model files and
  `flop_recipes.py`. `test_flop_models.py` (the brief's literal, unannotated pytest
  function bodies) trips 34 `ANN001`/`ANN201` findings. `pyproject.toml`'s
  `[tool.ruff.lint.per-file-ignores]` only exempts `tools/tests/**` from `ANN`
  ("Type hints are enforced for the tool (tools/xut), not for pytest test functions" --
  the stated intent already covers this file, the glob just predates `tests/` existing).
  `pyproject.toml` is infra-owned; I did not touch it. Recording this as the AGENTS.md §13
  TODO: an infra branch should widen that per-file-ignore glob to `"{tools/tests,tests}/**"`
  (or equivalent) so work-unit test files get the same ANN exemption as `tools/tests/**`.
  Fixed the one mechanical, non-ANN finding (`I001`, import order) with
  `ruff check --fix --select I001`.
- `uv run xut lint`: 0 issues. `uv run xut lint --branch`: 0 issues.
- Fast suite: `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: **1288 passed, 1
  skipped** in 96.47s (log kept in `.cache/LOG`, git-ignored). The 1 skip is the async-ctrl
  test above; every other repository test (`tools/tests`, plus the new flops tests) is
  green.

## Next steps

- Task 21: extend `flop_recipes.py` with the stimulus recipes (`all_configs`, `Flop`,
  `attr_names`, `inv`, `BIN`, `generators`) and the FDRE `.xvec`/cocotb wiring.
- Tasks 25/26: add the FDSE model, then FDCE/FDPE (first async controls -- this is where
  `test_gsr_versus_async_control_inferred_control_wins`'s disagreeing branch actually runs).
- Infra TODO above: widen the ruff `per-file-ignores` ANN exemption to cover
  `tests/**/test_*.py`.
