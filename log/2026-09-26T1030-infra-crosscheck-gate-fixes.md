# 2026-09-26: PR D gate fix wave (crosscheck evidence, S23, per-configuration coverage)

## What changed
- `xut crosscheck`:
  - A model source whose results disagree on `tree_hash`, or include one with `dirty` not `false` or no tree hash, is not compared. It is reported as a "mixed/stale provenance" issue, and `--write-findings` writes nothing for that test.
  - A test counts as compared only when two results share a configuration that both ran. Traces that share none are an issue, never `agree`. A configuration that only one simulator ran gets a coverage note.
  - An `expected_divergence` that names a finding whose `Status:` is not `open` is an issue.
  - Exit codes (ruling S23): 0 clean, 3 unlisted finding (wins over 4), 4 incomplete. 1 and 2 keep their generic meanings.
- Shared result reader `xut.results.read_result` (schema-validated), used by crosscheck and `status record`. A `pass` or `fail` that ran no configuration is unusable: an issue in crosscheck, an `error` in record.
- `status record`:
  - reads each result once;
  - credits vector coverage per configuration that passed on the golden model and on at least one simulator, using that configuration's own `bins_reached` (the python runner now records it per configuration) and its crosses.
- Lint `expected-divergence` also requires that the finding file exists and is `Status: open`.
- `xut.testspec` now holds the runner/flow rule (`runner_flows`, `declared_runners`, `SIMULATORS`, `RUNNER_ORDER`) and `finding_status`. `xut.formats.common.int_literal` is the one Verilog literal parser.
- Provenance takes three git calls per stamp and is cached per `xut run`.
- PROGRESS legend names the runner at each position of a level cell. TODO wraps bin lists at 100 columns.
- UG953 allowed-value lists are no longer capped at 120 characters. ICAPE2 `DEVICE_ID` now lists all 51 values; the catalog was regenerated and only ICAPE2 changed.
- Spec rev 3.4: §8, §9 and §11 now state rulings S17 and S19–S23.

## Tests
- `-m "not slow" -n 8`: 1271 passed.
- crosscheck container + vivado end-to-end: 2 passed.
- ruff and `xut lint` (plain and `--branch --base infra/sim-runners`) are clean.

## Next steps
- Orchestrator, on main after merge: `xut status init --refresh-bins` (it also refreshes ICAPE2's DEVICE_ID bins). Then drop the TEMPORARY `pre_s19` and `REGENERATED_ON_BRANCH` allowances in `test_status_schema.py`.
- Rebase onto PR C: the spec status line and revision history both gained a line after "(S8′)." Keep rev 3.3, then 3.4.
