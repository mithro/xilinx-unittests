# 2026-09-26 03:45 — Overnight progress: Step 1 complete, Step 2 PR A/B underway

## Merged to main
- PR #1 spec rev 3 (Verilator `deassign` transform, openXC7 nextpnr, fasm2bels spike).
- PR #3 Step 2 plan (27 tasks) + spec rev 3.1 (Verilator v5.048 from source; expected divergences never mask).

## Step 1 bootstrap (PR #2, branch infra/bootstrap) — both gate reviewers approve; NOT YET PUSHED
- 9 tasks + final fix wave: xut CLI, UG953 fetcher, pyslang UNISIM parser (504 unisims + 871 retarget parse),
  UG953 catalog for all 103 primitives, work units (28), AGENTS.md, review prompts, templates, commit hook,
  status schema/stubs/PROGRESS/TODO/LOG generation, lint (branch ownership, rename-safe), doctor, UNISIM submodule.
- 232 tests. Notable review catches: port descriptions from neighbouring table rows; ownership collision
  between infra and unit overrides; git rename detection hiding moved files from ownership lint;
  DSP48E1.C misclassified as a clock.

## Step 2 (stacked local branches)
- infra/sim-formats (PR A, tasks 1-5): xut-sim container (Icarus 12.0, Verilator 5.048, cocotb 2.0.1),
  .xvec timed stimulus, .xtr traces + x-aware comparison, xut wrap, validator + VecBuilder.
  Both gate reviews requested changes (shared name grammar, in-memory Vec checks, tool-version failures,
  free-clock hw renderability — ruling S8 revised to S8′); fix wave in progress.
- infra/sim-runners (PR B, tasks 6-11): Task 6 golden-model API + replay complete (review found and fixed
  co-timed wide-port intermediate-value bug; per-bit provenance).

## Blockers
- GitHub push: ssh-agent has no identities; gh token lacks `workflow` scope (CI file changed). Owner action needed.
- fpgas.online per-board SSH ports unreachable from this host ("No route to host"); needs owner input before Step 3.

## Potential findings to confirm
- RAMB18E1 and MMCME2_ADV UNISIM models reject their documented default attribute values at elaboration.
