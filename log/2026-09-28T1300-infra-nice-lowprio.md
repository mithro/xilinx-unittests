# infra/nice: heavy work runs at low CPU and I/O priority

## What changed (host rule, requested by the user through local-f3)

- **`xut heavy`.** The scope's command runs under `nice -n 19 ionice -c2
  -n7` (`heavy.LOW_PRIORITY`), a prefix inside the scope. `systemd-run
  --scope` never execs its command, so `-p Nice=` and `IOScheduling*` would
  do nothing there.
- **Docker.** Every container xut starts gets `--cpu-shares=128` and
  `--cpus=2` (`XUT_CONTAINER_CPUS`), and its command runs under
  `nice -n 19`. Two CPUs are the most any of our tools uses (Verilator's
  `-j 2`); at 24 containers that leaves more than 40 of the 88 CPUs free.
- **Parallelism check.** It now counts a tool's options only after the tool's
  own word, so `nice -n 19 uv run pytest -n 8` counts 8, not 19 (bug found
  by the crosscheck agent).
- **AGENTS.md §10.1.** New "Low priority" bullet, and the scope command line
  now shows the prefix.

## Verified live, through `xut heavy` from this branch

- In the scope: `ps -o ni,cls` gives `NI 19 CLS TS`, and `ionice -p` gives
  `best-effort: prio 7`.
- For a container xut started (`DockerExecutor.run`):
  `/sys/fs/cgroup/system.slice/docker-<id>.scope/cpu.weight` = 5, and
  `cpu.max` = `200000 100000`, which is 2 CPUs.

## Tests

`test_container`, `test_heavy`, `test_portability` and `test_runner_iverilog`
(`-n 2`, through `xut heavy`): 273 passed. They include:
- the new docker argv test: shares, cpus, the nice prefix, and the
  `XUT_CONTAINER_CPUS` validation;
- the scope argv test with the prefix.

The heavy tests, with the new parallelism cases, pass as well.
