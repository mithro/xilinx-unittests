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

## Fix round 1 (correctness review of PR #18)

- **[must-fix] `--vivado N` (ruling).** It reserves N × 16G inside the 96G.
  The scope gets `XUT_HEAVY=1` and `XUT_HEAVY_VIVADO=N`.
  `xut.heavy.vivado_reserved()` refuses (fails closed) when the caller is not
  under `xut heavy` or reserved 0. Step 3's `scoped_run` must call it before
  starting its own 16G scope. §10.1 now says a Vivado/xsim run is covered by
  the caller's `--mem` when it runs in the caller's scope, and by `--vivado`
  when it runs in its own 16G scope.
- **Nits:**
  - Order: the claim is now "a gate holder is never overtaken"; waiters on
    the gate are not FIFO.
  - The parallelism check also covers `-j`, `-jN` and `bash -c`/`sh -c`
    scripts. It is documented as best effort, and `--containers` is the
    caller's declaration.
  - Nested `xut heavy` is refused.
  - A missing `$XDG_RUNTIME_DIR` is an error, not a fallback directory.
  - §10.1 notes that containers can outlive a killed command until swept.
  - §10.1 notes that the old-style flock can wait a long time.
- **Also:** `--expand-environment=no` on the scope. systemd 257 warned that it
  will expand `$VAR` in scope command lines in the future, which would change
  commands such as `bash -c 'echo $HOME'`.
- **Tests:** `pytest tools/tests/test_heavy.py tools/tests/test_unitkit.py
  tools/tests/test_cli.py`: 65 passed, 3 runs out of 3.
- **End to end with real systemd-run:**
  - `--vivado 1` took 5 tokens, and the scope saw `XUT_HEAVY=1` and
    `XUT_HEAVY_VIVADO=1`;
  - a nested `xut heavy` inside it was refused (exit 1);
  - `bash -c 'echo HOME=$HOME'` printed the real home.

## Fix round 2 (code-quality review of PR #18)

- **[must-fix]** The E501 at `test_heavy.py:130` is fixed, so `ruff check
  tools models` is clean. CI's tooling job had stopped before pytest.
- **Parallelism detector.** It is now tool-aware:
  - pytest's `-n`/`--numprocesses` counts only in a pytest command,
    including `python -m pytest`;
  - `--jobs` counts only in an xut command;
  - `-j`/`--jobs` counts only in a make or ninja command.

  A `bash -c` script is split into its commands at `;`, `&&`, `|` and the
  like, so `tail -n 50`, `head -n`, `git log -n` and `sort -n` no longer
  count. There are new cases for each.
- **Refactor.** `admit`'s token loop is extracted as `_take_tokens`, and the
  held tokens are kept in a dict keyed by index.
- **`--mem`.** It is normalised once in `run()` (uppercase) for both the
  budget and `MemoryMax`.
- **Threading tests.** They no longer use sleeps: each admission is observed
  through `admit`'s `log` messages (waiting for the gate, the tokens or the
  old mutex, then admitted), with `Event.wait` and a check that each thread
  ended.
- **Lock-passing probe.** The child now takes each passed token lock
  exclusively without blocking, which it can only do because it holds that
  very lock.
- **Docs.** `NativeExecutor`'s docstring points at `xut heavy`. AGENTS.md
  §10.1 is rewrapped, and the scope command is a code block.
- **Tests.** `test_heavy`, `test_unitkit`, `test_cli` and the non-container
  `test_container`: 154 passed, 5 runs out of 5, in a capped scope. ruff is
  clean.
