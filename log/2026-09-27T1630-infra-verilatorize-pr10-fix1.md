# infra/verilatorize — PR #10 fix round 1

Branch `infra/verilatorize`, from 831ea94. Orchestrator rulings S50 (fail closed:
refuse what cannot be proven) and S51 (portability `config` category).

## What changed

Correctness must-fixes (reviewer (b)); each counterexample is a regression test:

1. NBA cone through a helper instance: `analyze` traces a helper output's cone
   inside the same-file helper; an NBA-written reg there refuses the rewrite
   (S28), an undeterminable driver refuses the model. Fixtures
   `vz_bad_nbahelper.v` (VZNBASUB) and `vz_bad_nbahelper4.v` (VZCES).
2. Transitive child verdicts: `driver.descendant_configs` elaborates a gated
   model's hierarchy under a configuration and records each transformed
   descendant's parameterisation (`ModelEntry.dep_configs`). `ensure_model`
   derives it and checks the descendants; `--check` schedules those child
   configurations; `blocked` (runner), and the portability `equiv` cell need
   every descendant's pass, and name the child and its verdict. Fixture
   `vz_dsp.v`/`vz_dspe1.v` (the DSP48 over DSP48E1 AREG=0 shape).
3. The sv guard elaborates with the configuration's `-G` values; an attribute
   that is not a testbench parameter fails closed.
4. The sv guard gates every UNISIM model instance of the testbench (refused
   first, from the preprocessed syntax; then each gated one for its own
   parameterisation; then the S38 check of each testbench-level instance).
5. `disable`/`break`/`continue`/`return` are no longer fall-through: refused
   while an override is pending, in a block or task that forces a reg, or as a
   `disable` of a forcing block. Fixture `vz_bad_disable.v` (VZDIS).
6. z-driving testbench variables: `sv_nets` follows variable writes
   (initialisers, procedural and continuous assignments, port outputs; task
   outputs and `$fscanf`-style writes fail closed). cocotb: `XutDut` refuses a
   z write and (under `XUT_NO_Z`, set for verilator/iverilog-vz) a z read back
   on `in_vec`/`clk`; `cocotb_check` reports it as an error.

Code-quality must-fixes (reviewer (a)):

- CQ1: portability category `infra-error` (host exception, docker exit 125);
  the reason carries the note; lint asks for the table to be regenerated.
- CQ2: `xut.slots.vivado_slot` (4 flock slots under
  `$XDG_RUNTIME_DIR/xut-vivado/`, `XUT_VIVADO_SLOTS`) around
  `xsim.run_script` and `xsim_version`.
- CQ3: lint reuses `_valid_test_files`.

S51: portability category `config` (a model's own attribute check refused the
smoke configuration; patterns from the real 2025.2 logs) rendered as
`no: config: ...`, counted in its own column, a lint warning not an error; a
missing module absent from the model source (B_ISERDESE2, B_GT*, BM_NOC_*) is
`secureip`.

Nits: `_equiv` needs every default/generate key; lint matches rows by the
catalog's model file; reverse (unsupported with no matching row) and no-row
warnings; walking-one/zero trigger stimulus; exit 137 labelled
timeout-or-kill; gated models under `ctx.defines` fail closed; an iverilog-vz
transform-bug records the Verilator pass as error; typing; one short-HEAD and
size parser; `parse` refuses unknown cells; `run_smoke` split; missing tests;
`model_attrs` keys a bit vector by value.

## Test results

- Sweep of every forced UNISIM model (analyze + rewrite, both sources): no
  change from must-fixes 1 and 5.
- Descendant derivation on every real gated parent (both sources): no
  elaboration errors; e.g. DSP48 needs DSP48E1 `ADREG=0,DREG=0,INMODEREG=0`,
  MULT18X18S needs DSP48E1 with every register 0.
- Re-classification of the S50 full run's logs (no re-run): 2025.2 iverilog
  313 yes / 183 no / 19 config, verilator 249 / 264 / 2; 2020.1 iverilog
  161 / 71 / 17, verilator 127 / 120 / 2.
- Full suite: see the report (`pr10-fix1-report.md`).

## Next steps

- Re-run `xut portability` on main after merge (the tool hash changed: every
  model is re-transformed and re-checked, and descendant configurations such
  as DSP48E1 ADREG=0 get their own verdicts).
- Legal smoke configurations from the units' `smoke_attrs` overrides (S51.5).
- Plumbing `ctx.defines` into the transform and the check (parked; refused
  for gated models meanwhile).
