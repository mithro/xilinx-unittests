# infra/verilatorize: equivalence stimulus and original-vs-transformed check (Task 14)

## What changed
- `tools/xut/verilatorize/equiv.py`: `equiv_stimulus` builds the mandatory stimulus in four phases (independent, coincident with clock edges, pairs, with async activity). `check_model` runs the transformed model on Icarus and the original on the oracle chosen under ruling S31: Icarus for constant overrides that Icarus runs cleanly, xsim otherwise. xsim unavailable is an error.
- Driver: `verilatorize(check=True)`, `equiv` and `equiv_oracle` in the manifest. CLI: `xut verilatorize --check`, which exits 1 on any fail or error.
- Task 13 minors: `tool_sha256` hashes every xut module the package imports, transitively, plus the vector testbench (M1). A crash still ends with `progress: done=total` (M2).
- `runners/xsim.render_script` gains `glbl`, `libs` and `sourcelibdirs`, so the oracle compiles the model source's own model file.
- Fixtures: `vz_cea.v` (VZCEA, now in MODS, 16 fixtures) and `vz_guard.v` (VZGUARD).

## Test results
- vz, xsim runner, slow, container and vivado tests: 288 passed. Fast suite: 1293 passed. `xut lint --branch --base infra/sim-runners`: 0 issues.
- Real check, `--check --jobs 24`, about 1 minute per source:

  | Source | pass (iverilog oracle) | pass (xsim oracle) | fail | error |
  |---|---|---|---|---|
  | unisim-2025.2 | 43 | 19 | 0 | 12 |
  | unisim-gh-2020.1 | 43 | 17 | 0 | 12 |

- FDRE, FDSE, FDCE and FDPE pass in both configurations, in both sources.
- The errors, which are the same in both sources:
  - DSP48E1: 6 illegal single-attribute configurations. The model's own attribute check stops both sides at 1 ps.
  - FIFO18E1/FIFO36E1: 2 configurations each. The model's reset-protocol DRC stops both sides at 203 ns; 17 samples agree before the stop.
  - OSERDESE1: 2 configurations. Icarus 12 cannot compile the model, and the original fails the same way.
- VZIFELSE fixture: 1 mismatch against xsim. It is a race in the original under a coincident C2/E change, and the test pins it.

## Next steps / TODO
- A ruling on the VZIFELSE race (class nondeterminism).
- FIFO and DSP48E1 need per-primitive stimulus constraints, or a ruling. Until then, Verilator is blocked for those configurations.
- The `.xvec` header cannot hold string attributes. This affects every string-attribute vector test.

## Fix round 1 (review of cee25bd..eab8433)
- A missing or identical transformed copy is now an error. Both models are compiled explicitly, and `-y` serves only dependencies.
- The redo key now includes the simulator versions (`equiv_tools`).
- `config_key` is injective.
- `check_model` never raises.
- The Icarus runner's `step()` is public.
- The xsim oracle compiles the UNISIM originals without `-sv`.
- The `_coincident` docstring now says it uses rising edges only.
- Tests: 294 vz/xsim tests (slow, container and vivado) and 1293+6 fast tests pass; lint reports 0 issues.
- Real check re-run on both sources: 43/19/0/12 and 43/17/0/12. The per-result lines are identical to the earlier run.
