# SPDX-License-Identifier: Apache-2.0
"""The CI container-test shards (xut.ci_shards) partition ``-m container`` exactly."""

import re
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
    for k in range(ci_shards.SWEEP_CHUNKS):  # each chunk shard: its chunk of both sources
        lints = [t for t in shards[f"sweep{k}"] if "_lints[" in t]
        assert sorted(lints) == sorted(
            f"{ci_shards.SWEEP}[{src}-{k}]" for src in ci_shards.SWEEP_SOURCES
        )
    assert ci_shards.SWEEP_MANIFEST.split("::")[1] in " ".join(shards["sweep0"])
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


def _sim_shard() -> dict:
    return yaml.safe_load((repo_root() / ".github/workflows/ci.yml").read_text())["jobs"]


def test_workflow_runs_every_shard_and_reports_sim():
    jobs = _sim_shard()
    matrix = jobs["sim-shard"]["strategy"]["matrix"]["shard"]
    assert sorted(matrix) == sorted(ci_shards.SHARDS)
    assert jobs["sim-shard"]["strategy"]["fail-fast"] is False
    runs = [s for s in jobs["sim-shard"]["steps"] if "ci_shards.py" in s.get("run", "")]
    assert len(runs) == 1
    step = runs[0]
    assert step["env"]["SHARD"] == "${{ matrix.shard }}"
    # the arguments go through a file: a failing ci_shards.py fails the step (bash -e)
    # instead of leaving an empty argument list (which would run the whole suite)
    lines = step["run"].splitlines()
    assert lines[0].startswith("python3 tools/xut/ci_shards.py") and "> " in lines[0]
    assert lines[1].startswith("mapfile -t args < ") and "<(" not in step["run"]
    gate = jobs["sim"]  # the check name every PR reports
    assert gate["needs"] == "sim-shard" and gate["if"] == "${{ !cancelled() }}"
    assert gate["steps"][0]["env"]["RESULT"] == "${{ needs.sim-shard.result }}"
    assert 'test "$RESULT" = success' in gate["steps"][0]["run"]


def test_flops_steps_run_in_exactly_one_shard():
    """Review must-fix: the flops `xut run`/`xut crosscheck` steps name one shard that
    exists (FLOPS_SHARD), so renaming or mistyping it can never make them run nowhere."""
    assert ci_shards.FLOPS_SHARD in ci_shards.SHARDS
    steps = _sim_shard()["sim-shard"]["steps"]
    flops = [s for s in steps if "'unit:flops'" in s.get("run", "")]
    assert len(flops) == 2  # xut run, then xut crosscheck
    assert any("xut run 'unit:flops'" in s["run"] for s in flops)
    assert any("xut crosscheck 'unit:flops'" in s["run"] for s in flops)
    for s in flops:
        named = re.findall(r"matrix\.shard == '([^']*)'", s["if"])
        assert named == [ci_shards.FLOPS_SHARD], s["if"]
        assert "!=" not in s["if"].split("&&")[1]  # one shard, never "all but one"
    others = [s for s in steps if s not in flops]
    assert not any("matrix.shard" in s.get("if", "") for s in others)  # every leg runs them


def test_sweep_shards_match_the_sweep_test():
    """The per-chunk sweep shards name the chunks and sources the sweep test has."""
    import test_vz_rewrite as vr

    assert ci_shards.SWEEP_CHUNKS == vr.SWEEP_CHUNKS
    assert list(ci_shards.SWEEP_SOURCES) == [s for s, _ in vr.SWEEP_SOURCES]
    assert [k for k in ci_shards.SHARDS if k.startswith("sweep")] == [
        f"sweep{k}" for k in range(vr.SWEEP_CHUNKS)
    ]
