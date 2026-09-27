# infra/perf-lock: heavy commands admitted by memory budget

## What changed

- New `xut heavy --mem <cap> --containers <n> --name <what> -- <command>`
  (`tools/xut/heavy.py`).
  - It admits a heavy command while the sum of the budgets of all running
    heavy commands stays at most 96G. A command's budget is its scope cap plus
    its containers times the container cap.
  - It then runs the command in the usual capped `systemd-run` scope in
    `vivado.slice`, and exits with the command's exit code.
  - **Tokens.** The budget is 24 flock tokens of 4G under
    `$XDG_RUNTIME_DIR/xut-heavy.d/`, taken under a gate so that the head of
    the queue is admitted first (no starvation, no deadlock). The tokens pass
    to the command (`pass_fds`), as flock(1) does.
  - **Old mutex.** It holds the old `xut-heavy.lock` shared, so old-style
    `flock` commands still run alone.
  - **Refusals.** It refuses `-n auto`, a `--jobs`/`-n` in the command above
    `--containers`, and a budget over 96G.
- AGENTS.md §10.1:
  - the "one heavy command at a time" bullet becomes "admission by memory
    budget";
  - a table of the measured scope peaks, from `journalctl --user`, with
    suggested `--mem` values.
- `unitkit.run_block` (README "How to run") uses `xut heavy --mem 8G
  --containers 16`.

## Why

Wait-time report 002: the single mutex made small jobs, such as a reviewer's
2-file pytest, wait up to 8 minutes behind a full suite. The measured scope
peaks are far below the caps:

| Job | Scope peak | Cap |
|---|---|---|
| unit `xut run` | 1.4G | 32G |
| full pytest `-n 8` | 2.5G | 32G |
| targeted pytest | 0.2–0.7G | 16G |

## Tests

- `pytest tools/tests/test_heavy.py tools/tests/test_unitkit.py
  tools/tests/test_cli.py`: 54 passed. `test_heavy.py` passed 3 times out of
  3, which checks the threading tests for flakiness.
- The tests cover:
  - token arithmetic, parallelism parsing and budget refusal;
  - concurrent admission, waiting and head-of-queue order;
  - old-mutex interplay, lock passing and the CLI exit code.
- End to end, with a real systemd-run: `uv run xut heavy --mem 1G
  --containers 0 --name perf-heavytest -- bash -c '...; exit 5'` ran in
  `vivado.slice/xut-perf-heavytest-*.scope` and exited 5.
- ruff, `xut lint`: clean.

## Next steps

- The orchestrator rolls it out to the agents' briefs. Old-style flock keeps
  working meanwhile.
- A possible follow-up is `xut heavy --status`, showing who holds how many
  tokens.
