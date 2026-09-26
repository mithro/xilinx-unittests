# 2026-09-26: xut status record, bins-accounted lint, shared unit test paths (Task 18)

## What changed
- `xut status record PRIM... | --unit NAME [--model-source NAME]` fills `status/<family>/<PRIM>.yaml` from `xut run`'s `result.json` files:
  - `results` keys are `<level>/<runner>/<flow>` for python, xsim, iverilog, verilator and hw, for every flow a test declares. A declared flow that has not run yet (vivado, yosys, openxc7, vpr) is `not-run`.
  - The golden model (`python`) only has `rtl` keys. `hw` never has `rtl` keys.
  - A cell's value is the worst over the primitive's tests, in the order `fail > error > pass > not-run > unsupported > n/a > skip`.
  - `measured.tree_hash` covers the primitive's tests, `_shared/<unit>`, both golden-model files and the catalog overrides. `record` refuses to run while any of these has uncommitted changes.
  - `coverage.covered` has two parts:
    - vector `exercises` that the golden model confirms in `bins_reached`;
    - the `exercises` of sv/cocotb tests that passed on at least one simulator.
  - A declared bin that the golden model does not reach gives a warning.
  - `findings` lists the open `findings/<PRIM>-*.md` stems.
  - The reference source `unisim-2025.2` fills `results`. Any other source fills `results_by_model_source.<source>`, and `measured.model_sources` lists both. PROGRESS.md adds `+gh` to a level where the submodule source disagrees on pass/fail.
- `tests/<family>/<group>/_shared/<unit>/**` is now owned by the unit, and `TestCase.shared_dirs` returns that directory. The cocotb tests no longer monkeypatch it.
- New lint rules:
  - `bins-accounted`: every catalog bin is in some test's `exercises` or starts a `gaps` entry;
  - `gaps-present`: every test has a non-empty `gaps`.
- pytest also collects `tests/`, which holds the unit-owned model and generator tests. It skips `sv/`, `cocotb/` and `vectors/`.
- `xut run` / `xut crosscheck` with `unit:<name>` for a unit that has no tests yet selects nothing and exits 0. `xut crosscheck --model-source` limits the report to one source.
- CI's `sim` job runs the flops L0/L1 vector tests on iverilog against `unisim-gh-2020.1`, then crosschecks them. Both steps do nothing until PR E.

## Tests
- `-m "not slow" -n 8`: 1194 passed (was 1153). ruff and `xut lint` (plain and `--branch --base infra/sim-runners`) report no issues.

## Ruling S19 (port × class and declared-cross bins)
- `coverage_bins` adds a `port:<P>:<event>` bin for each port class, and `cross:<A>=<a>,<B>=<b>` bins for the `crosses` a catalog override declares.
- The golden replay's `Reach` reports these port events.
- `status record` counts a cross bin as covered when a configuration that ran and passed has those values.
- FDRE now has 20 bins, or 28 once the pilot adds its 8 claims.

## Next
- The committed status stubs predate S19. Each gains the new bins when its unit first records.

## Review fix round 1 (rulings S20, S21)
- `xut status init --refresh-bins` rewrites the bins of stubs that have never been recorded. Recorded status files stay byte-identical. The orchestrator should run it on main after merging.
- Every `result.json` from `xut run` now carries `tree_hash`, `head` and `dirty`. `status record` refuses a result that is stale or was measured on a dirty tree.
- Each model source keeps its own tree hash and tools. PROGRESS.md marks a source recorded at another tree hash with `~gh`, and a runner that passed some flows but not all with `◐`.
- A vector test's bins now count only if a simulator also passed it.
- A gap accounts for a bin only when its leading token is exactly that bin. A blank gap is an error.
- `crosscheck --model-source` refuses a model source it does not know.
- Fast suite: 1223 passed.
