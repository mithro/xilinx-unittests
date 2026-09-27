# infra/perf-xsim-standalone: xsim runs a standalone snapshot

## What changed

- `tools/xut/runners/xsim.py`: `render_script` elaborates with
  `xelab ... --standalone` and runs the snapshot's own executable
  (`xsim.dir/xut_snap/axsim`, with `$XILINX_VIVADO/lib/lnx64.o` on the loader
  path) in place of `xsim xut_snap -R`. The same compiled snapshot runs to the
  end; only xsim's Tcl shell start-up is gone. The verilatorize xsim oracle
  shares `render_script`, so it gets the same speed-up.
- `tools/tests/test_runner_xsim.py`: the script test pins the new run step.

## Why (measured from existing logs)

- The flops unit run on unisim-2025.2 (Task 27, `--jobs 16`) took 925 s. xsim is
  the critical path: 8465 of 11742 runner-thread seconds, behind 4 host Vivado
  slots. Per configuration (file mtimes, 284 configurations), xvlog took 2.2 s,
  xelab 2.4 s and the `xsim -R` run 6.7 s, of which the simulation itself took
  about 1.5 s of CPU.
- `xsim -help` alone takes 2 s: most of the run step is the Tcl session.

## Results

- One configuration (FDRE L1 capture): the run step went from 6.6 s to 1.8 s,
  with a byte-identical `raw.txt`.
- Benchmark: `xut run '7series.FDRE.*' --model-source unisim-2025.2 --runner
  xsim --jobs 16`, a clean `build/rtl`, in a detached worktree at the flops
  branch (9cc4eb9). Before: 258 s. After: 168 s (-35%). The mean run step went
  from 6.7 s to 1.85 s.
- The results are identical. All 23 `result.json` match in status, reason, and
  per-configuration status, reason and trace sha256. All 154 `trace.xtr` and
  65 `raw.txt` are byte-identical.
- `pytest -n 4 tools/tests/test_runner_xsim.py tools/tests/test_vz_equiv.py`
  (Vivado present): 116 passed, including the $fatal, $error, reject
  end-to-end, early-end, generic and oracle tests.
- A probe showed that the standalone executable prints `Fatal:` and exits 0
  after `$fatal`, as `xsim -R` does. `$stop` ends it without `XUT_DONE`.
  Nothing uses `$stop`.

## Next steps

- The first run after the merge redoes the verilatorize equivalence checks
  once. The transform's tool hash covers `xut.runners`, by design.
- Heavy-lock semaphore (`infra/perf-lock`, wait report 002).
