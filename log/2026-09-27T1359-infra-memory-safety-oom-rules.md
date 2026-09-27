# infra/memory-safety: memory-safety rules (AGENTS.md §10.1)

## What changed
- Added AGENTS.md §10.1. Heavy commands run in capped `systemd-run --user --scope`
  units in `vivado.slice`, containers are capped with docker `--memory`, and
  parallelism is sized from measured memory.
- Why: on 2026-09-26 at 20:25 ACST, a `xut portability --jobs 80` run container
  peaked at 471.6 GiB. The cause was runaway Verilator `--timing` smoke sims of
  DPLL, IDELAYE3 and ODELAYE3. systemd-oomd could not see the container, which was
  in system.slice, so it killed 17 tmux pane scopes, including every agent session.

## Measurements (2026-09-27)
- The worst normal xut container peaked at 2.4 GiB (from the journal, over 174 containers).
- A Verilator smoke build peaks at about 0.45 GiB.
- DPLL, IDELAYE3 and ODELAYE3 smoke sims were each OOM-killed under a 4 GiB
  container cap within seconds; IDELAYE3 reached 2.9 GiB at t+9 s.

## Tests
- Docs only. `xut lint --branch` passes.

## Next steps
- The container cap itself (`DockerExecutor --memory`) lands on
  infra/verilatorize (Task 16b).
