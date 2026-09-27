# SPDX-License-Identifier: Apache-2.0
"""The CI container-test shards (xut.ci_shards) partition ``-m container`` exactly."""

import subprocess
import sys
from pathlib import Path

import yaml

from xut import ci_shards
from xut.paths import repo_root


def _collect(select: list[str]) -> list[str]:
    """The node ids pytest selects with ``select`` (collection only, no xdist)."""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly", *select],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return [ln for ln in p.stdout.splitlines() if "::" in ln]


def test_shards_partition_the_container_tests():
    everything = _collect(["-m", "container"])
    assert len(everything) > 50  # the collection itself worked
    shards = {name: _collect(sel) for name, (sel, _) in ci_shards.SHARDS.items()}
    seen = [t for ids in shards.values() for t in ids]
    assert sorted(seen) == sorted(everything)  # every test once: none dropped, none twice
    assert shards["sweep"] and all("test_sweep_every_transformed_model_lints" in t
                                   for t in shards["sweep"])  # fmt: skip
    assert shards["verilator"] and all(
        t.startswith("tools/tests/test_runner_verilator.py::") for t in shards["verilator"]
    )


def test_cli_prints_one_argument_per_line():
    p = subprocess.run(
        [sys.executable, str(Path(ci_shards.__file__)), "rest"], capture_output=True, text=True
    )
    assert p.returncode == 0 and p.stdout.splitlines() == ci_shards.args("rest")
    bad = subprocess.run(
        [sys.executable, str(Path(ci_shards.__file__)), "nope"], capture_output=True, text=True
    )
    assert bad.returncode == 2
    assert "from xut" not in Path(ci_shards.__file__).read_text()  # stdlib only


def test_workflow_runs_every_shard_and_reports_sim():
    jobs = yaml.safe_load((repo_root() / ".github/workflows/ci.yml").read_text())["jobs"]
    matrix = jobs["sim-shard"]["strategy"]["matrix"]["shard"]
    assert sorted(matrix) == sorted(ci_shards.SHARDS)
    assert jobs["sim-shard"]["strategy"]["fail-fast"] is False
    runs = " ".join(s.get("run", "") for s in jobs["sim-shard"]["steps"])
    assert "tools/xut/ci_shards.py" in runs and "matrix.shard" in runs
    gate = jobs["sim"]  # the check name every PR reports
    assert gate["needs"] == "sim-shard" and gate["if"] == "always()"
    assert "needs.sim-shard.result" in " ".join(s.get("run", "") for s in gate["steps"])
