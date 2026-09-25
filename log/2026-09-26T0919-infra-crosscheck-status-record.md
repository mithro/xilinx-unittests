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
- `-m "not slow" -n 8`: 1183 passed (was 1153). ruff and `xut lint` (plain and `--branch --base infra/sim-runners`) report no issues.

## Next
- Port × class and declared-cross coverage bins (Ruling 20) need a design decision. The FDRE pilot plan expects 21 bins, which is the current bin set, and the golden model's `Reach` records neither kind.
