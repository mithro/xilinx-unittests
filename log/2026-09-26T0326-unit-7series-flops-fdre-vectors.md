# Task 21: shared stimulus recipes, FDRE L0-L2 vector tests, test.yaml/README generator

Branch `unit/7series/flops`, starting HEAD `174e7d7`. Commits: `227b77e`
(Task 20 re-review fix round 2), `e7af26f` (shared recipes + generator),
`2a54e29` (FDRE vector tests, test.yaml, README).

## What changed

- `models/xut_models/7series/_common/flops.py`: Task 20 re-review round-1
  findings R2/R3/R4 were test-strength gaps with a correct model behind
  them, so no model change was needed there. R5 needed a real fix:
  `set_input`/`clock_edge` now raise `ModelContractError` if called before
  `power_on()`, and `set_input` raises for any value other than 0/1.
  `xut.golden.replay` always calls `power_on()` first and `_port_value`
  already intercepts x/z before it ever reaches `set_input`, so neither
  guard changes golden-replay behaviour; they only stop a direct/misbehaving
  caller (e.g. a future cocotb driver) from producing silently-wrong state.
- `tests/7series/register/_shared/flops/test_flop_models.py`: added the R2
  (`test_c6_not_hit_from_gsr_edge_probe`), R3
  (`test_c7_not_hit_when_ce_low`, `test_c7_not_hit_when_control_active`), R4
  (`test_c5_control_force_on_inverted_edge`) and R5
  (`test_set_input_before_power_on_is_rejected`,
  `test_clock_edge_before_power_on_is_rejected`,
  `test_input_value_other_than_0_or_1_is_rejected`) tests. Verified against
  the reviewer's mutation harness (copied into the scratchpad,
  `mutate2.py` with the N1-N9 revert-one-fix mutants): all 9 original
  mutants and all 9 fix-round mutants, N2/N6/N9 included, are now killed.
  24 -> 31 tests, all passing (1 still skipped: the async-only S30 test has
  no primitives until Task 26).
- `tests/7series/register/_shared/flops/flop_recipes.py`: completed per the
  brief's Step 1 (`all_configs`, `Flop`, the L0-L2 recipes, `generators`).
  Two deviations from the brief's literal code:
  - `l0_illegal_init` needed `illegal=["INIT"]` on `ctx.dut(...)`; without
    it `xut.validate` refuses the reject stimulus ("reject config must name
    its illegal attribute"), which the brief's own code omits.
  - `generators()`'s per-recipe closure used a `(lambda fn: lambda ctx:
    fn(ctx, k))(fn)` IIFE to avoid Python's late-binding trap; `ruff` still
    flags it `B023` (a known limitation reading that idiom). Replaced with
    `functools.partial(fn, k=k)`, which is both clean and warning-free.
- `tests/7series/register/_shared/flops/flop_tests.py`: written per the
  brief's Step 3, with the exercises lists reworked for ruling S33 (the
  brief's `_ports()`/20-bin count is superseded: FDRE's catalog carries 28
  bins, the 8 claims plus S19's port x class bins). Added `_class_bins`
  (reads `xut.status.port_class_bins` for one catalog port -- never
  hand-rolled), `_reach` (specific event(s) of one port) and `_reach_all`
  (every class bin of a port, kind-agnostic: `0`/`1` for a `data` control
  like FDRE.R, `assert`/`release` for an `async` one like FDCE.CLR, since
  `_reach_all` is what stays correct for FDSE/FDCE/FDPE too, even though
  only FDRE's files are committed this task -- `test_every_test_has_gaps`
  calls `tests_for()` for all four kinds).
  Each test's added class bins were checked against a direct
  `xut.golden.replay` probe of each recipe (aggregated over its
  configurations) before writing them, then re-checked against the real
  `xut run --runner python` `result.json` `bins_reached` after generation
  (see below). Two things the probe surfaced that pure reading of the
  recipes would have missed:
  - `VecBuilder.set()` is a no-op when the port's value doesn't change from
    the builder's own tracked default (0); only `VecBuilder.init()` always
    emits. So e.g. `l0_smoke` never actually drives `D:0` (every config's
    `1 - init` XOR `inv_d` that would need it lands back on the builder's
    starting 0), and `l1_gsr`'s `D` value is constant per config, so only
    one of `D:0`/`D:1` shows up depending on which config computes to 1.
  - `Flop.__init__`'s `b.init(**{k.ctrl: self.inv_ctrl})` always reaches
    `R:0` or `R:1` (whichever `inv_ctrl` is) even in recipes that never
    otherwise touch the control (e.g. `l1_capture`), because `init()`
    doesn't check for change the way `set()` does. Ruling S33's own
    `l1_capture` example (`C:edge, CE:1, D:0, D:1`) reads as "at least
    these", not "only these": `R` is left out of that test's *named* ports
    in the brief's own `_ports(k, "C", "CE", "D", "Q")` call (no `R`), so no
    `R` class bin is added there either -- the rule this task follows is
    "add the class bins of exactly the ports a test already names, filtered
    to what its own recipe is confirmed to drive", which reduces to the
    ruling's example exactly for `l1_capture` and generalises cleanly to
    every other test.
- `tests/7series/register/_shared/flops/test_flop_tests.py`: written
  verbatim per the brief's Step 3.
- `tests/7series/register/FDRE/vectors/gen.py`: written verbatim per the
  brief's Step 2.
- `tests/7series/register/FDRE/test.yaml`, `README.md`: generated by
  `flop_tests.py FDRE`; committed as-is (`test_committed_files_are_current`
  keeps them in sync).

## Test results

- `uv run pytest -q tests/7series/register/_shared/flops`: 28 passed, 1
  skipped (the async-only S30 test).
- `uv run xut run '7series.FDRE.*' --runner python`: all 11 vector tests
  `pass` (`L0.illegal_init` included, once `illegal=["INIT"]` was added);
  `L1.sv_gsr_midsim`, `L1.sv_x_inputs`, `L2.cocotb_random` `skip` with their
  declared unsupported reasons.
- Reach-confirmation (ruling S23/S33): for every one of the 11 vector
  tests, every bin in its declared `exercises` is present in its own
  `build/rtl/python/unisim-2025.2/<id>/result.json` `bins_reached` (checked
  programmatically after the run; zero missing bins on every test).
- `uv run xut lint`: 0 errors, 42 warnings, all `tests-documented`
  `related id '...' does not exist` for FDSE/FDCE/FDPE test ids that don't
  exist until Tasks 25/26 -- exactly the brief's expected shape, and no
  `bins-accounted` error (all 28 catalog bins accounted for: 27 via some
  test's `exercises`, `claim:FDRE.C8` via `L1.is_d_inverted`'s `gaps`).
- `uv run xut lint --branch`: same 42 warnings, 0 errors; branch-paths and
  generated-files (the two checks `--branch` adds) contribute nothing new,
  i.e. the branch stayed inside `owned_paths(flops)`. Note for whoever reads
  this: the total isn't literally "0 issues" because the 42 pre-existing
  `related` warnings are unaffected by `--branch` mode (that check runs
  over the whole tree in both invocations) -- they are not new to this
  branch and will clear once FDSE/FDCE/FDPE land.
- `uv run ruff format` + `uv run ruff check` on every new/changed file: 0
  issues outside `ANN*` (missing type annotations) on files under `tests/`,
  which is the documented infra gap; fixed the one non-ANN finding
  (`B023`, see above) and 4 `I001` import-order findings via
  `--fix`. `models/xut_models/7series/_common/flops.py` and
  `tests/7series/register/FDRE/vectors/gen.py` are fully clean, no ANN
  exceptions needed.
- `uv run pytest -q -n 16 -m "not slow" tools/tests tests`: 1304 passed, 1
  skipped (`.cache/fast-suite.log`).

## A brief/spec discrepancy worth recording

Step 5's "Expected" says `L1.gsr_init`'s `stim.xvec` should be
`hw_renderable yes` ("GSR is renderable per spec §5.2 (the runner
declaration covers the §7.2 limitation)"). The current spec on `main`
(rev 3.4, §5.1) says the opposite: "GSR needs the GSR-immune harness
(§7.2), so until step 3 builds it, a GSR event also makes the file
`hw_renderable: no`." The actual run gives `hw_renderable no reason="...glbl
GSR on hardware needs the GSR-immune harness (spec §7.2; step 3)..."`,
matching the current spec, not the brief. Per AGENTS.md §1 ("the current
spec on `main` is authoritative"), this is followed as-is and flagged here
rather than treated as a bug; `L1.gsr_init`'s own `runners=_runners(hw=
HW_GSR)` already declares `hw: unsupported` for the same spec §7.2 reason,
so nothing needed to change.

## Next steps

- Tasks 25/26 (FDSE, then FDCE/FDPE) reuse `flop_recipes.py`/`flop_tests.py`
  unchanged; `_reach_all`'s class-agnostic design means FDCE/FDPE's async
  `CLR`/`PRE` (`assert`/`release` bins) need no new code in
  `tests_for()`.
- The 42 `related`-warning baseline clears once those units land.