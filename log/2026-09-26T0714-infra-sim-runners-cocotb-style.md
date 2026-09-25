# 2026-09-26: Task 11, the cocotb style on the iverilog runner

## What changed
- `xut.cocotb_dut.XutDut`: a map-aware handle on `xut_cocotb_top`.
  - It keeps Python-int shadows of `clk` and `in_vec` and writes the whole vector on each change.
  - Spacing matches VecBuilder: every operation is followed by a 1 ns gap (or the map's `min_event_gap_ps`), and `settle()` waits until 120 ns.
  - `sample`/`close` write `.xtr` through `xut.formats.xtr`.
  - The default header comes from `XUT_RUNNER`/`XUT_MODEL`/`XUT_SEED` plus prim/cfg from the map.
- `tools/xut/hdl/cocotb_run.py`: the in-container launcher (`cocotb_tools.runner`, Icarus or Verilator).
- The iverilog runner has a cocotb branch:
  - `write_dut(..., cocotb_top=True)` from the catalog entry;
  - the launcher runs in the container;
  - `cocotb_check` classifies the result from `results.xml`: AssertionError is `fail`; SimFailure or any other exception is `error`; a missing results.xml or failed build is `error`; a seed mismatch or a trace header that does not match the run is `error`.
- `executor_for(model_source, work_root)` mounts a run root outside the checkout at `/xut-root`, so container tests can use tmp_path.
- New TOYFF fixture test `7series.TOYFF.L2.cocotb_capture`. ToyDff moved to the fixture's `_shared/toy/toy_golden.py`.

## Tests
- Full suite (container + vivado): 1039 passed (11m21s).
- `test_runner_cocotb.py`: 30 passed (7 container tests, ~10 s).
- ruff format/check are clean. `xut lint --branch --base infra/sim-formats`: 0 issues.
- Demo (`xut run --runner python --runner iverilog --style cocotb --seed 7`): python skip, iverilog pass.

## Next
- Task 15: the Verilator runner reuses `cocotb_command(..., "verilator", x_seed=...)`. A manual probe shows the TOYFF cocotb fixture passes on Verilator 5.048 through the launcher.
- Task 18: `TestCase.shared_dirs`. The cocotb tests monkeypatch Task 18's rule until it lands.
