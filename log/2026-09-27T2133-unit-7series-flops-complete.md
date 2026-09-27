# flops Task 27: whole-unit verification (PR E)

Branch `unit/7series/flops`, rebased by the orchestrator onto main `143c16f`
(PR #13, the crosscheck iverilog-vz companion fix, is merged). HEAD at the start:
`9cc4eb9`, identical to `origin/unit/7series/flops`.

Rulings applied:

- `--jobs 16` (not the brief's 40);
- every heavy command ran under `flock $XDG_RUNTIME_DIR/xut-heavy.lock` in a
  `vivado.slice` scope with `MemoryMax=32G` and `MemorySwapMax=0`
  (`status record` at 4G);
- `pytest -n 8`;
- unisim-gh-2020.1 ran every runner that exists for it: python, iverilog, verilator
  and iverilog-vz;
- crosscheck must exit 0.

No UNISIM source was opened, and no test was changed.

## What changed

Nothing in the tree except this log entry:

- `rm -rf build/rtl` (this worktree's own build dir), then a full re-run of
  `unit:flops` on both model sources.
- `xut status record --unit flops` for both sources rewrote the four status files
  byte-for-byte identically.
  - The rebase did not change any primitive's tree hash.
  - The results equal the ones already recorded in fix round 1 (`958f39f`).
  - So there is no "record whole-unit results" commit.

## Run

| step | start (UTC) | duration | results |
|---|---|---|---|
| `xut run 'unit:flops' --model-source unisim-2025.2 --jobs 16` | 20:56:02 | 925 s | 290 |
| `xut run 'unit:flops' --model-source unisim-gh-2020.1 --runner python --runner iverilog --runner verilator --jobs 16` | 21:11:27 | 464 s (about 200 s of that waiting for the heavy lock held by another session's pytest) | 232 |
| `xut run 'unit:flops' --model-source unisim-gh-2020.1 --runner xsim --jobs 16` | 21:20 | about 20 s | 58 xsim skips, plus 46 python re-runs |
| `xut crosscheck 'unit:flops'` | 21:19:11 and 21:21 | under 1 min each | exit 0 both times |
| `pytest -q -n 8` (whole suite, including slow) | 21:22:44 | 689 s | 2031 passed, 2 skipped |

- The explicit `--runner` list on gh-2020.1 left xsim `not-run: declared, but no
  result.json` in the first crosscheck.
- So I ran `--runner xsim` on gh-2020.1. Each xsim cell now carries its reason, as
  in the pilot:
  - `skip: runner unavailable: xsim uses Vivado's precompiled unisims_ver`;
  - or the declared cocotb skip.
- Crosscheck was then re-run. The second run, also exit 0, is the one reported
  below.

Progress (60 s cadence, from the run script's own progress log):

- 2025.2: 78/290 at 20:57:02; 147 at 21:00:03; 218 at 21:04:03; 276 at 21:07:03;
  289 at 21:11:04; done at 21:11:27.
- gh-2020.1: waited on the heavy lock until about 21:14:30; then 97/290 at 21:15:27
  (232 expected with the explicit runner list), 212 at 21:17:28; done at 21:19:11.

## Results

rtl flow, per primitive, model source and runner (FDRE and FDSE have 13 tests,
FDCE and FDPE 16):

| prim | source | python | xsim | iverilog | verilator | iverilog-vz |
|---|---|---|---|---|---|---|
| FDRE | 2025.2 | 10 pass, 3 skip | 12 pass, 1 skip | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDSE | 2025.2 | 10 pass, 3 skip | 12 pass, 1 skip | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDCE | 2025.2 | 13 pass, 3 skip | 14 pass, 1 fail, 1 skip | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDPE | 2025.2 | 13 pass, 3 skip | 14 pass, 1 fail, 1 skip | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDRE | gh-2020.1 | 10 pass, 3 skip | 13 skip (unavailable / cocotb) | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDSE | gh-2020.1 | 10 pass, 3 skip | 13 skip (unavailable / cocotb) | 13 pass | 12 pass, 1 skip | 12 pass, 1 skip |
| FDCE | gh-2020.1 | 13 pass, 3 skip | 16 skip (unavailable / cocotb) | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |
| FDPE | gh-2020.1 | 13 pass, 3 skip | 16 skip (unavailable / cocotb) | 15 pass, 1 fail | 14 pass, 1 fail, 1 skip | 14 pass, 1 fail, 1 skip |

- Every fail is `L1.gsr_vs_clear` (FDCE, INIT=1) or `L1.gsr_vs_preset` (FDPE,
  INIT=0) at samples S2, S3, S4 and S9, where GSR and the control are both active.
- Skips are all declared:
  - sv on python;
  - cocotb on python and xsim;
  - `sv_x_inputs` on verilator and iverilog-vz.
- This is identical to the Task 24 pilot.

Crosscheck `xut crosscheck 'unit:flops'`: **exit 0, "56 agree, 2 known-divergence"**.

- `7series.FDCE.L1.gsr_vs_clear` is `known-divergence (of doc-gap, finding
  FDCE-doc-gap-L1-gsr_vs_clear)`:
  - 8 points on unisim-2025.2 (iverilog, verilator, xsim);
  - 8 points on unisim-gh-2020.1 (iverilog, verilator).
- `7series.FDPE.L1.gsr_vs_preset` is the same, with `FDPE-doc-gap-L1-gsr_vs_preset`.
- iverilog-vz's fails are now explained through their iverilog companion (PR #13),
  and no issue remains. No transform-bug was reported.

`xut status record --unit flops` (both sources):

- 2025.2: FDRE/FDSE 12 pass, 48 not-run; FDCE/FDPE 9 pass, 3 fail (L1 on xsim,
  iverilog and verilator), 48 not-run. Coverage is 27/28 each; only
  `claim:<PRIM>.C8` (a placement rule) is uncovered.
- gh-2020.1: FDRE/FDSE 9 pass, 51 not-run; FDCE/FDPE 7 pass, 2 fail, 51 not-run.
- Each status file has `results`, `results_by_model_source.unisim-gh-2020.1`, both
  entries in `measured.model_sources`, and one tree hash per primitive shared by
  both sources.

`xut lint --branch`: 0 errors and 4 warnings. All four are the known
`portability-agreement` warnings on `L1.sv_x_inputs` (verilator declared unsupported
for an x stimulus, which the lint text names as a valid reason).

## Findings (all open)

- `findings/FDCE-doc-gap-L1-gsr_vs_clear.md`: UG953 p369 does not order GSR
  against an active CLR. The model infers that CLR wins, and UNISIM gives INIT.
- `findings/FDPE-doc-gap-L1-gsr_vs_preset.md`: the same for PRE (p372).
- `findings/FDPE-doc-gap-doc-init_default.md`: the p373 table gives INIT default
  1'b1, and the p374 templates show 0. The model follows the table, and no trace
  disagrees.
- `findings/FDSE-doc-gap-doc-init_default.md`: the same contradiction (p379 against
  p380).

## Next steps

- PR E: "flops: FDRE/FDSE/FDCE/FDPE pilot", with sequential reviewers.
- After the merge, the orchestrator regenerates `status/*.md` on `main`.
- Step 3: silicon evidence for the GSR-vs-control doc-gap. The GSR tests stay
  `hw: unsupported` until the §7.2 GSR-immune harness state exists.
