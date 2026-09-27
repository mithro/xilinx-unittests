# infra/verilatorize: memory-capped containers (Task 16b, Ruling S48)

## What changed
- `tools/xut/container.py`: `DockerExecutor(memory=...)` defaults to `$XUT_CONTAINER_MEMORY`, else `4g`. The value is validated against `^[0-9]+[kmg]$`, and anything else raises `XutError`. Every `docker run` gets `--memory=<m> --memory-swap=<m>`. `--rm` is gone. After every run, whether it returns, times out or raises, `_finish` checks `docker inspect -f '{{.State.OOMKilled}}'`. When that is true, it appends `xut-container: oom-killed at memory cap <m>` to the log and keeps the exit code. It then runs `docker rm -f`. A failure in either cleanup step is written to the log and never raised. New constants: `OOM_MARK`, `MAX_JOBS = 64`.
- The OOM check runs after **every** run, not only when the exit code is 137. A probe on docker 26.1 showed why: the kernel killed the largest process in the container, `bash` survived and the container exited 0, yet `OOMKilled` was `true`. The portability scripts are in exactly this situation: `simx` is killed and `verilator.sh` still writes `rc 137` and exits 0.
- `tools/xut/portability.py`: `driver.sh`, its template and the `xargs -P` call are gone. `_run_scripts` runs one container per smoke script, using a `ThreadPoolExecutor(max_workers=jobs)` in `jobs.txt` order (slowest first). Each container's log is `<tool>.container.log`. The `progress: done=` lines still appear every 10 s.
- After an OOM kill, the host copies the oom line into `<tool>.log`. If the script had not yet written `<tool>.rc`, the host writes `137` there and adds the script's line to `done.txt`. A host-side `RunTimeout` writes `124` and the timeout mark.
- A new category, `oom`, is checked before `timeout`. For an OOM, `failure()` uses the oom line, so the reason names the cap.
- `tools/xut/cli.py`: `xut run` and `xut portability` refuse `--jobs` above 64 with the message "the memory budget is 100G ÷ 4G per container". Both defaults are already 1, below `min(cpu, 24)`, so they are unchanged.

## Test results
- New tests: argv flags, env and constructor override, 8 malformed caps, OOM with rc 137 and OOM with rc 0, no OOM, container removal on timeout, exception and rm failure, plus a live `container` test in which a 64m cap OOM-kills python and the run returns 137 with the line in the log. Portability tests: `_run_scripts` with a fake executor (at most `jobs` at once, start order, early and child OOM, host timeout), the `oom` classification, and the `--jobs 65` refusal for both commands.
- Full suite, `pytest -n 8`, including the container tests: 1507 passed in 8m30s. `test_container.py` and `test_portability.py` were re-run after the final formatting: 95 passed.
- `xut lint --branch --base infra/sim-runners`: 0 errors, 1 warning (PORTABILITY.md is not generated yet; expected off main).
- Live check: `xut portability --models '[DFI][DPE][LRE][LEA]*' --jobs 8` on 7 models (DPLL, FDRE, IDELAYCTRL, IDELAYE2, IDELAYE2_FINEDELAY, IDELAYE3, IDELAYE5), 32 configurations and 64 scripts. The smoke phase took 48 s; the whole run took 94 s.
  - FDRE: `yes`/`yes`.
  - DPLL and IDELAYE3: verilator `no`, with the reason `oom: xut-container: oom-killed at memory cap 4g [default]`.
  - Every other model and every iverilog cell: `yes`.
  - No `xut-` containers were left behind.
- The Task 16 partial results in `build/portability/unisim-2025.2` were moved aside during the live check and then restored. The live run's work directory is in `build/portability/t16b-live-unisim-2025.2`.

## Incident during this session
- My first red-phase run of the new `--jobs 65` CLI tests had no guard. Because the refusal did not exist yet, they started a real `xut run` and `xut portability` over everything, though inside the 16G user scope. I stopped the run after about 2 minutes, during the `verilatorize --check` phase: the scope held, no container was left, the manifest is valid and `build/portability` was never touched. The tests now monkeypatch `run_smoke`/`run_tests` to raise, so a missing check can never start a real run.

## Next steps / TODO
- `run_smoke` still deletes `build/portability/<source>/` on a `--models` (partial) run, which removes a full run's work logs. Partial runs should get their own work directory.
- The step-2 plan (docs/superpowers/plans, lines 5414-5415) still describes `driver.sh`/`xargs`. It was left as a historical record.
- `xut verilatorize --jobs` has no upper bound. Its containers are capped now.

## Fix round 1 (review of 52e3c64..318ca87, orchestrator rulings S48a)
- **I-1.** The cap is parsed to bytes and must be 64m to 32g. `0g`, `00g`, `1k` and `33g` raise `XutError`, which names the range.
- **I-2.** `XUT_MEMORY_BUDGET` (default `100g`, same syntax) divided by the cap (`max_jobs()`) replaces `MAX_JOBS=64`, giving 25 at the defaults. The refusal names the budget, the cap and the limit. The defaults stay at 1, and a test pins them to at most min(cpu, 24, limit).
- **I-3.** The limit applies to `run`, `portability` and `verilatorize`. A test walks every `--jobs`/`-j` option. The refusal tests stub every real run.
- **M-1.** `docker rm -f` runs in a `finally` around the inspect. Live containers are tracked. On Ctrl-C, `run_tests`, `_run_scripts` and the verilatorize equiv pool cancel their queues and call `kill_live()`.
- **M-2.** Every container has the labels `xut.owner=<pid>` and `xut.session=<uuid>`, and runs under an in-container `timeout -k 10 <timeout_s + 30>`. The extra 30 s lets the host timeout (a `RunTimeout`) fire first, so a timed-out run is never nondeterministically reported as rc 124. `xut doctor --sweep-containers` removes containers whose owner is dead. Live test: an orphan with a dead owner was removed and one with a live owner was kept.
- **M-3.** `OOM_MARK` is in `reject.INFRA`, so an OOM kill is always `error` and never a rejection.
- **M-4.** In its own commit: a partial run works under `build/portability/partial/<ms>/`.
- **M-5.** A script that writes no rc gets `xut-container: exit <rc>: <last line>`, which shows in the reason.
- **M-6.** The `NativeExecutor` docstring says the native path is uncapped and must run inside a capped scope.
- **M-7.** Every script is counted in `done.txt` exactly once. The default-jobs test now has a real bound.
- **Tests:** full suite, `pytest -n 8` with the container tests: 1553 passed. Lint: 0 errors.
- **Live check 2** (same 7 models, `--jobs 8`): the smoke phase took 52 s. FDRE: yes/yes. DPLL and IDELAYE3: `oom: ... memory cap 4g`. The work went to `partial/unisim-2025.2/`, and the Task 16 directory was untouched. No containers were left.

## Fix round 2 (re-review R-1..R-4)
- **R-1.** `kill_live()` sets a module-level `_HALT` under `_LIVE_LOCK` before taking its snapshot. `DockerExecutor.run` checks `_HALT` in the same critical section as `_LIVE.add` and raises `RunCancelled` (a `KeyboardInterrupt` subclass) instead of starting. As a result, a container is either killed or never started, even when a job issues several runs in sequence.
  - Tests: a run after the halt refuses and never calls `docker run`. A stress test runs 8 threads that start runs in a loop and checks that every `docker run` issued after the halt belongs to the snapshot; it passed 25 of 25 repeated runs.
  - An autouse fixture clears the halt after each test.
- **R-2.** A budget below the cap is now a `XutError` ("... is below the container cap ...").
- **R-3.** Containers carry the label `xut.host=<hostname>:<boot_id>`. The sweep filters on it, and any rm failures are reported together at the end.
  - Live test: an orphan labelled with this host was removed, and one labelled with another host was kept.
- **R-4.** Removed the dead worker-side `KeyboardInterrupt` handler.
- **Tests:** full suite, `pytest -n 8` with the container tests: 1557 passed.
- **Live Ctrl-C:** `timeout -s INT 70 xut portability --models ... --jobs 8` was interrupted mid-smoke at done=12/64. It aborted promptly and left no `xut` containers.
