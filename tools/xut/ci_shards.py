# SPDX-License-Identifier: Apache-2.0
"""The CI ``sim`` job's container tests, split across parallel jobs (shards).

Measured on CI run 36353909339: the container tests took 424 s on one 4-vCPU runner,
bound by two items that ``--dist loadfile`` keeps on a single worker:

- ``test_vz_rewrite.py::test_sweep_every_transformed_model_lints`` (358 s alone);
- ``test_runner_verilator.py`` (10 tests, 323 s in sequence on one worker).

Each gets a runner of its own; ``test_runner_verilator.py`` is spread over that runner's
workers test by test (``--dist load``: its tests are ``tmp_path``-hermetic). Everything
else stays in ``rest`` with ``--dist loadfile``, as before.

The shards partition the container tests exactly: ``test_ci_shards.py`` collects each
shard and the whole ``-m container`` set and checks that every test is in exactly one
shard, so a new container test lands in ``rest`` and none is ever dropped.

Stdlib only. ``python3 tools/xut/ci_shards.py <shard>`` prints the shard's pytest
arguments, one per line (the workflow reads them with ``mapfile``).
"""

from __future__ import annotations

import sys

SWEEP = "tools/tests/test_vz_rewrite.py::test_sweep_every_transformed_model_lints"
#: The shard that also runs the flops ``xut run`` and ``xut crosscheck`` steps; the
#: workflow names it in those steps' ``if`` and ``test_ci_shards.py`` pins that exactly one
#: shard, this one, runs them.
FLOPS_SHARD = "rest"
VERILATOR = "tools/tests/test_runner_verilator.py"

#: shard -> (selection, scheduling). Selection decides which tests run; scheduling only
#: how they are spread over the runner's workers.
SHARDS: dict[str, tuple[list[str], list[str]]] = {
    "sweep": (["-m", "container", SWEEP], []),
    "verilator": (["-m", "container", VERILATOR], ["-n", "auto", "--dist", "load"]),
    "rest": (
        ["-m", "container", "--deselect", SWEEP, "--ignore", VERILATOR],
        ["-n", "auto", "--dist", "loadfile"],
    ),
}


def args(shard: str) -> list[str]:
    """The full pytest arguments of ``shard`` (``-v`` for the CI log)."""
    select, sched = SHARDS[shard]
    return ["-v", *sched, *select]


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SHARDS:
        print(f"usage: ci_shards.py {{{','.join(SHARDS)}}}", file=sys.stderr)
        return 2
    print("\n".join(args(argv[0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
