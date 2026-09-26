# infra/verilatorize: Verilator runner and iverilog-vz (Task 15, ruling S35)

Timestamp is UTC.

## What changed

- `tools/xut/runners/verilator.py` (new):
  - `VerilatorRunner` runs the vector, sv and cocotb styles, with `x_observable=False`.
  - `x_seeds`, `blocked`, `build_failure`, `verilator_argv`, `config_attrs`.
  - `IverilogVzRunner`: Icarus with `vz_dir` first on the library path. It skips a model that verilatorize refused ("model not transformed: ...").
- `tools/xut/verilatorize/driver.py`:
  - `vz_dir(ms, root)`, and `verilatorize(..., out_dir=)`.
  - `ensure_model`: transforms the model on demand, then runs the equivalence check for each configuration the manifest has no verdict for. It is cached per process, with a per-model lock and a manifest lock.
  - `model_attrs`: only the parameters the model declares, rendered as literals.
  - `ModelEntry.equiv_reason`.
- `runners/sim.py`: `ContainerSim` holds the shared available/tools/container code; `IverilogRunner` uses it.
- `run.py`: `with_companions` means `verilator` always brings `iverilog-vz`, both in `run_tests` and in the CLI. The default runner list now includes verilator and iverilog-vz.
- `hdl/cocotb_run.py`:
  - prints `XUT_COCOTB plusargs: ...`, so every seed's log records the X seed.
  - Verilator no longer gets `-Wno-lint -Wno-style`, per S35.5: warnings stay in the log, and `-Wno-fatal` keeps them non-fatal.

## Decisions

- **glbl (Step 1 spike):** glbl stays a second top.
  - On Verilator 5.048, with `-Wno-MULTITOP`, the toy DUT gave S0/S1/S2 = 1/1/0 (and 1/0/1 for the glbl-GSR stimulus).
  - `-G` still reaches the sv top when glbl is a second top (probe).
  - The FDRE hand check used the real 2025.2 `glbl.v` as the second top.
  - Pinned by `test_glbl_mode`.
- **S35.1:**
  - `unsupported` gives `verilatorize cannot transform ...`.
  - An equivalence `fail` gives `transform-bug: ...`.
  - An equivalence `error`, or a missing verdict, gives `equivalence check error for <PRIM> <cfg>: <reason> blocks ...`.
  - An `expect=reject` configuration is gated on the `default` configuration's verdict, because its own attributes are illegal and no verdict can exist for them.
- **S35.2:** an x/z vector stimulus is an error ("2-state simulator cannot apply x stimulus"). The check runs before the expected trace is looked up.
- **Both X seeds are compared with expected.xtr.** The brief compares only the first seed. Comparing both is stricter: a seed that gets a defined bit wrong fails the configuration.
- **S35.3, tristate root cause:**
  - Verilator's V3Tristate lowers `P === 1'bz` on an input port into a comparison of `P__en`, which turns the input into a tristate.
  - For a module below the top, the instance pin then needs `P__out`, which an input does not have. Verilator reports "Unsupported: tristate in top-level IO" (a misleading message).
  - Wrapper variants did not matter: a bit select, a whole port and an intermediate wire all fail.
  - The cause is inherent to Verilator combined with the model's own `CE === 1'bz`/`R !== 1'bz` (11 compares in FDRE). The transform is not the cause.
  - 186 of the 2025.2 UNISIM models compare something with `1'bz`.
  - The runner reports the error with an explanation. A test covers it: a toy model with `D !== 1'bz`.
- **S35.4 (M3):** test `test_vpi_release_coincident_with_an_edge_matches_the_vector_testbench`.
  - On transformed VZTRIG, a CLR/PRE release written through cocotb/VPI in the same step as a rising C, in both write orders, gives the same Q as the vector testbench.
  - That also equals the original on Icarus: forced 0, release+edge 1, retain 1.
  - **No difference was found.**
- **S35.5:** build directories are `cfg-*/` under the run root, with `obj/` and `build.log`. The verilatorized models live in `<run root>/build/verilatorized/<source>/`. No new waiver flags were added.

## Results

- **S35.6, FDRE hand check.** Scratch root; unit files copied there only. Logs: scratchpad `t15/fdre-handcheck2.log` and `t15/fdre-handcheck-patch.log`.
  - python, iverilog and iverilog-vz: all 7 L1 vector tests pass.
  - On-demand equivalence: 9 FDRE configurations, all `pass`.
  - verilator: `error` on all 7, from the inherent tristate issue above (CE).
  - Prototype: with the 11 z-compares of the scratch vz copy rewritten to their 2-state constants, verilator **passes all 7, with x_dependence false**.
- Tests:
  - `test_runner_verilator.py`: 22 hermetic and 8 container tests, all pass.
  - Runner, vz and container suites, slow included: 599 passed (`.cache/t15-wide.log`).
  - Fast suite (`-m "not slow" -n 16`): 1329 passed (`.cache/t15-fast2.log`).
- `ruff format --check`, `ruff check` and `xut lint --branch --base infra/sim-runners`: 0 issues.

## Next steps / TODO

- **Needs a ruling:** extend verilatorize with a Verilator-only rewrite of z compares on input ports, `(P === 1'bz)` → 0 under `ifdef VERILATOR`.
  - Without it, no FD* (and probably many of the 186 models) can pass on Verilator.
  - It is a spec §6.2 change: models that are otherwise `unchanged` would also need the rewrite and an equivalence check.
- The verilator result for `TOYFF.L0.reject` (INIT=1'bx) passes. Verilator rejected at runtime.
- Log timestamps: this entry uses UTC (TODO S219).

## Round 2 (ruling S38, concern 2)

- **What changed**
  - New module `verilatorize/zcmp.py`. It rewrites an input port compared with z (`P ===/!== <z literal>`, either operand order, whole port or a select) to the constant a driven input gives. The rewrite is unconditional. Any other z-literal comparison is refused.
  - A model that needs only this rewrite is now `transformed`. `ModelEntry.rewrites` records which rewrites were applied: `shadow` and/or `zcmp`.
  - The validity condition (every input driven) is guarded: the equivalence check, the runners and sv testbench instances all make an undriven input or a z stimulus an `error`.
  - The equivalence stimulus has a new `_inputs` phase for zcmp models.
  - `ensure_model` now records `sim_tools` with each on-demand verdict, and rechecks a missing, errored or stale verdict the same way `--check` does.
- **Sweep with `--check`**
  - unisim-2025.2: 157 transformed (zcmp 130, shadow 17, both 10), 1166 unchanged, 52 unsupported (34 of them new z-compare refusals). Verdicts: 113 pass on the Icarus oracle, 18 pass on xsim, 1 fail (ODELAYE5), 89 error.
  - unisim-gh-2020.1: 94 transformed, 125 unchanged, 30 unsupported. Verdicts: 88 pass on Icarus, 17 pass on xsim, 0 fail, 49 error.
- **The ODELAYE5 fail is an Icarus-vs-xsim divergence, not the transform.** The transformed copy, both shadow-only and with S38, matches the original on xsim at all 134 samples.
- **Verilator lint:** 154/157 and 92/94 models are clean. In the wrapper lint, 110/140 and 61/77 models are clean, and every remaining failure is secureip or a refused dependency. No "tristate in top-level IO" error remains.
- **FDRE hand check:** verilator 7/7 pass with x_dependence false; iverilog-vz 7/7 pass.
- **Tests:** fast suite 1349 passed; runner/vz/container suites 619 passed; the sweep 2 passed. ruff and `xut lint` report 0 issues.
