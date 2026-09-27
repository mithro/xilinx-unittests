# flops Task 24: pilot run of FDRE, FDSE, FDCE and FDPE

Branch `unit/7series/flops`, rebased onto main `55a1cad`, starting at `eaafe13`.
Rulings applied:

- S40: all four flops;
- S42/S30: GSR against an active control is a doc-gap, and the model is kept;
- S44/S32: crediting;
- S50a: the Verilator/iverilog-vz companion.

The model sources are unisim-2025.2 (the reference) and unisim-gh-2020.1. The gh
submodule was already initialised in this worktree (`1c8e05f`), so no
`git submodule update` was needed. No UNISIM source was opened. Every heavy
command ran under `flock $XDG_RUNTIME_DIR/xut-heavy.lock` in a `vivado.slice`
scope with `MemorySwapMax=0`:

- `xut run` at `--jobs 16`, capped at 32G;
- crosscheck capped at 16G;
- `pytest -n 8` capped at 32G;
- lint and `status record` capped at 4G.

## What changed

- `L0.illegal_init` (INIT=1'bx, expect=reject) was checked first, on the committed
  inputs at `eaafe13`.
  - It failed on all four flops:
    - on iverilog and xsim with unisim-2025.2;
    - on iverilog with unisim-gh-2020.1.
  - The failure was "expected rejection, got acceptance: the run reached
    XUT_DONE", so UNISIM accepts INIT=1'bx.
  - UG953 lists the legal values but promises no runtime check. Following the
    brief, the test and its `l0_illegal_init` recipe are removed.
  - `L0.smoke` now records the gap: "UNISIM (unisim-2025.2 on iverilog and xsim,
    unisim-gh-2020.1 on iverilog) accepts INIT=1'bx without rejecting it; the
    reject path is not exercised for flops".
- New `L1.gsr_vs_clear` (FDCE) and `L1.gsr_vs_preset` (FDPE), from the recipe
  `l1_gsr_vs_ctrl` in `_shared/flops/flop_recipes.py`.
  - They cover INIT × IS_<ctrl>_INVERTED: 4 configurations each.
  - Sequence (A): GSR on, then the control, one clock cycle under both, GSR off,
    then the control off.
  - Sequence (B): the control on, then GSR, the control off, then GSR off.
  - These are the first committed stimuli that hold GSR and CLR/PRE active
    together (the Task 26 TODO).
  - Their exercises are reach-confirmed by `test_exercises_are_reach_confirmed`.
  - Each test lists its finding in `expected_divergence` (cls `doc-gap`, runners
    iverilog, verilator, xsim) and links it from `gaps`. `add()` in
    `flop_tests.py` gained an `expected_divergence` keyword.
  - `test.yaml` and README.md were regenerated for all four flops.
- Findings, all `Status: open`:
  - `findings/FDCE-doc-gap-L1-gsr_vs_clear.md` and
    `findings/FDPE-doc-gap-L1-gsr_vs_preset.md`:
    - UG953 p369/p372 says CLR/PRE overrides "all other inputs" and says GSR loads
      INIT, but never orders the two;
    - the model infers that the control wins (S30). UNISIM gives INIT (GSR wins)
      in both orders, on every simulator and both model sources;
    - the model is unchanged, and the bits stay defined.
  - `findings/FDPE-doc-gap-init-default.md` (renamed in fix round 1 to
    `findings/FDPE-doc-gap-doc-init_default.md`):
    - the p373 table gives an INIT default of `1'b1`, but the p374 VHDL and
      Verilog templates show INIT=0;
    - the model follows the table. UNISIM agrees: the `L1.capture` `default`
      configuration passes everywhere;
    - no trace disagrees, so this finding is in no `expected_divergence`.
- Order of work:
  - I wrote the two doc-gap finding files by hand from a pre-check run of the
    uncommitted test (`xut run '7series.FD*.L1.gsr_vs_*'`).
  - I committed them, with the `expected_divergence` entries, **before** the full
    run. That avoided a second full run for a tree-hash change.
  - The full-run crosscheck then matched them as `known-divergence` (below).

## Results

Run durations:

- unisim-2025.2: 290 results in 13 min 22 s (19:39:40-19:53:02 UTC);
- unisim-gh-2020.1: 290 results in 5 min 59 s (19:53:16-19:59:15 UTC; no xsim).

Results per primitive and model source, rtl flow (vector, sv and cocotb tests
together; FDRE and FDSE have 13 tests, FDCE and FDPE 16; FDRE/FDSE rows corrected in
fix round 1, M2):

| prim | source | python | xsim | iverilog | verilator | iverilog-vz |
|---|---|---|---|---|---|---|
| FDRE | 2025.2 | 10 pass, 3 skip | 12 pass, 1 skip | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDSE | 2025.2 | 10 pass, 3 skip | 12 pass, 1 skip | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDCE | 2025.2 | 13 pass, 3 skip | 14 pass, 1 fail, 1 skip | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDPE | 2025.2 | 13 pass, 3 skip | 14 pass, 1 fail, 1 skip | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDRE | gh-2020.1 | 10 pass, 3 skip | 13 skip (unavailable) | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDSE | gh-2020.1 | 10 pass, 3 skip | 13 skip (unavailable) | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDCE | gh-2020.1 | 13 pass, 3 skip | 16 skip (unavailable) | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDPE | gh-2020.1 | 13 pass, 3 skip | 16 skip (unavailable) | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |

- Every fail is `L1.gsr_vs_*`:
  - for FDCE with INIT=1 and for FDPE with INIT=0;
  - at samples S2, S3, S4 and S9, the points where GSR and the control are both
    active;
  - every one of those bits is `inferred:` (S30).
- Declared skips:
  - the sv tests on python;
  - cocotb on python and xsim;
  - `sv_x_inputs` on verilator and iverilog-vz (2-state; x stimulus).
- xsim on gh-2020.1 skips with "runner unavailable": xsim uses Vivado's
  precompiled unisims_ver.
- iverilog-vz confirms Verilator everywhere (S50a). No transform-bug was reported.
  On `gsr_vs_*`, iverilog-vz fails exactly as iverilog does.

Crosscheck, `xut crosscheck '7series.FD*' --write-findings`:

- **Exit 4**: "56 agree, 2 incomplete". It wrote no new finding stubs.
- The 56 other tests agree on both model sources.
- `L1.gsr_vs_clear` and `L1.gsr_vs_preset` report `known-divergence (of doc-gap,
  finding <PRIM>-doc-gap-L1-gsr_vs_<ctrl>)`:
  - 8 points on unisim-2025.2 (runners iverilog, verilator, xsim);
  - 8 points on unisim-gh-2020.1 (iverilog, verilator).
- The 4 issues that make the verdict "incomplete" are one per test and model
  source, each `rtl/iverilog-vz: fail not explained by any disagreement`. This is
  an **infra gap**:
  - `crosscheck._explained` accepts a fail only when its runner is among the
    finding's runners;
  - the finding's runners come from `SIMULATORS`, and iverilog-vz is not one of
    them;
  - so the known divergence never explains iverilog-vz's golden-model fail, even
    though that trace matches iverilog's exactly (no transform-bug);
  - an `expected_divergence` entry cannot fix this, because `_explained` reads the
    finding's runners, not the entry's.
  - TODO (infra, AGENTS.md §13): treat an iverilog-vz fail as explained when its
    iverilog companion's fail is explained and the two traces agree.

`xut status record FDRE FDSE FDCE FDPE`, for both model sources:

- Each primitive has one tree hash, the same for both sources.
- FDRE and FDSE: every rtl cell passes.
- FDCE and FDPE: `L1/{xsim,iverilog,verilator}/rtl: fail` (the doc-gap); L0 and
  L2 pass.
- The non-rtl flows and hw are `not-run`.
- Coverage is 27/28 for each primitive. Only `claim:<PRIM>.C8` is uncovered: it
  is a placement rule, not a simulation behaviour.
- `findings` lists the open findings.

Other checks:

- `pytest -q -n 8 -m "not slow" tools/tests tests`: 1980 passed, 2 skipped.
- `pytest tests/7series/register/_shared/flops/`: 152 passed, 2 skipped.
- `xut lint` and `xut lint --branch`: 0 errors and 4 warnings.
  - All four are `portability-agreement` warnings on the `L1.sv_x_inputs` tests,
    which declare verilator unsupported because of their x stimulus.
  - The lint text itself names x stimulus as a valid reason.

## Progress reports (60 s cadence)

- 2025.2: started 19:39:40.
  - Results: 72/290 at 19:40:40, 147 at 19:43:40, 221 at 19:46:40, 278 at
    19:49:41, 289 at 19:52:42.
  - Done at 19:53:02.
- gh-2020.1: started 19:53:16.
  - Results: 60/290 at 19:54:16, 186 at 19:56:16, 284 at 19:58:16.
  - Done at 19:59:15.

## Next steps

- Infra: explain iverilog-vz fails through their iverilog companion (above). After
  that fix, crosscheck of the unit should exit 0.
- Hardware (step 3): the GSR-vs-control doc-gap needs silicon evidence, and GSR on
  hw needs the §7.2 harness state.
- Task 27: the unit PR.
  - The per-task review of these commits is still to be done: this session was
    told not to start subagents.

## Fix round 1 (Task 24 review I1, M1, M2, M3)

Progress:

- 20:16:06 UTC fix1 re-run: FDSE and FDPE on unisim-2025.2 then unisim-gh-2020.1 (--jobs 16, 32G scope; estimate 6-8 min, then about 3 min)
- 20:17:06 UTC fix1-unisim-2025.2: 59/145 results, 58 s elapsed, about 1 min 25 s left, finish about 20:18 UTC
- 20:18:06 UTC fix1-unisim-2025.2: 85/145 results, 116 s elapsed, about 1 min 22 s left, finish about 20:19 UTC
- 20:19:06 UTC fix1-unisim-2025.2: 110/145 results, 176 s elapsed, about 0 min 56 s left, finish about 20:20 UTC
- 20:20:06 UTC fix1-unisim-2025.2: 134/145 results, 238 s elapsed, about 0 min 19 s left, finish about 20:20 UTC
- 20:21:07 UTC fix1-unisim-2025.2: 140/145 results, 293 s elapsed, about 0 min 10 s left, finish about 20:21 UTC
- 20:22:07 UTC fix1-unisim-2025.2: 141/145 results, 303 s elapsed, about 0 min 8 s left, finish about 20:22 UTC
- 20:23:07 UTC fix1-unisim-2025.2: 144/145 results, 398 s elapsed, about 0 min 2 s left, finish about 20:23 UTC
- 20:23:35 UTC fix1-unisim-2025.2: done in 449 s
- 20:24:07 UTC fix1-unisim-2025.2: 145/145 results, 448 s elapsed, about 0 min 0 s left, finish about 20:24 UTC
- 20:24:07 UTC fix1-unisim-2025.2: finished
- 20:24:35 UTC fix1-unisim-gh-2020.1: 29/145 results, 8 s elapsed, about 0 min 34 s left, finish about 20:25 UTC
- 20:25:35 UTC fix1-unisim-gh-2020.1: 119/145 results, 69 s elapsed, about 0 min 15 s left, finish about 20:25 UTC
- 20:26:35 UTC fix1-unisim-gh-2020.1: 140/145 results, 128 s elapsed, about 0 min 4 s left, finish about 20:26 UTC
- 20:27:17 UTC fix1-unisim-gh-2020.1: done in 222 s
- 20:27:36 UTC fix1-unisim-gh-2020.1: 145/145 results, 171 s elapsed, about 0 min 0 s left, finish about 20:27 UTC
- 20:27:36 UTC fix1-unisim-gh-2020.1: finished

Changes:

- **I1.** I checked the FDSE text against UG953 v2026.1. The p379 table gives INIT
  a default of `1'b1`, while the p380 templates show `INIT => '0'` and
  `.INIT(1'b0)`. So FDSE has the same contradiction as FDPE. FDRE (p376 `1'b0`,
  p377 0) and FDCE (p370 `1'b0`, p371 0) are consistent.
  - New finding: `findings/FDSE-doc-gap-doc-init_default.md`.
  - I corrected the FDPE finding's false statement that FDSE agrees.
- **M3 (ruling S56a).** Both INIT-default findings now use the level token `doc`:
  `FDPE-doc-gap-doc-init_default.md` and `FDSE-doc-gap-doc-init_default.md`. The
  FDPE file was renamed with `git mv`. The FDSE and FDPE READMEs are regenerated,
  and every link is updated.
- **M1.** Finding headers:
  - `First seen: <UTC date> at <head>`;
  - an `Also seen: rtl / unisim-gh-2020.1` line;
  - the GSR doc-gap Evidence now pastes the 8 crosscheck points per model source
    verbatim, plus a map of the samples.
- **M2.** The FDRE and FDSE rows of the result table above are corrected: each has
  13 tests.
- The READMEs changed, so the FDSE and FDPE tree hashes changed. FDRE and FDCE
  inputs are unchanged, and their recorded hashes stay current.

Re-run of FDSE and FDPE:

- unisim-2025.2: 145 results in 449 s, 129 pass, 12 skip, 4 fail;
- unisim-gh-2020.1: 145 results in 222 s, 103 pass, 39 skip, 3 fail.

The fails are exactly `FDPE.L1.gsr_vs_preset`, as before. FDSE passes every
declared cell.

Crosscheck:

- Exit 4: "56 agree, 2 incomplete". This is unchanged. The only 4 issues are the
  iverilog-vz explanation gap: `rtl/iverilog-vz: fail not explained`, for 2 tests ×
  2 model sources.
- That fix belongs to infra PR #13, not to this branch.
- Both GSR doc-gaps are `known-divergence`, with 8 points per model source.

`xut status record FDRE FDSE FDCE FDPE`, for both sources:

- FDSE and FDPE get new tree hashes, and their `findings` lists now name the
  renamed and new files.
- FDRE and FDCE are unchanged.

Checks:

- `pytest tests/7series/register tools/tests/test_status_schema.py`: 176 passed,
  2 skipped.
- `xut lint --branch`: 0 errors and 4 warnings, the same `sv_x_inputs` warnings as
  before.
