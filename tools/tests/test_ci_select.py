# SPDX-License-Identifier: Apache-2.0
"""CI job selection (xut.ci_select and .github/workflows/ci.yml): fail-safe path filter."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from xut import ci_select
from xut.paths import repo_root

SCRIPT = Path(ci_select.__file__)
GATE = "needs.changes.outputs.sim != 'false'"


@pytest.mark.parametrize(
    "files",
    [
        ["log/2026-09-28T0800-docs-x-y.md"],
        ["docs/superpowers/specs/s.md", "docs/superpowers/plans/p.md", "log/a.md"],
        ["README.md", "AGENTS.md"],
    ],
)
def test_docs_only_pull_requests_skip_sim(files):
    sim, why = ci_select.select("pull_request", files)
    assert not sim and "docs/logs only" in why


@pytest.mark.parametrize(
    "files",
    [
        ["tools/xut/run.py"],
        ["log/a.md", "tools/xut/run.py"],  # one code file is enough
        ["models/xut_models/7series/fdre.py"],
        ["tests/7series/flops/FDRE/test.yaml"],
        ["containers/sim/Dockerfile"],
        ["catalog/7series/FDRE.yaml"],
        ["status/7series/FDRE.yaml"],
        [".github/workflows/ci.yml"],
        ["docs/work-units.yaml"],  # read by xut: not a doc
        ["docs/templates/primitive-README.md"],
        ["docs/review/code-quality.md"],
        ["findings/FDRE-x.md"],  # crosscheck reads findings
        ["tests/7series/flops/FDRE/README.md"],  # only the top-level README is a doc
        ["log/notes.txt"],  # only .md logs
        ["newdir/whatever"],  # unknown: everything
        ["pyproject.toml"],
        ["uv.lock"],
        ["third_party/XilinxUnisimLibrary"],
    ],
)
def test_any_other_path_runs_everything(files):
    sim, why = ci_select.select("pull_request", files)
    assert sim and "everything runs" in why


def test_doubt_runs_everything():
    assert ci_select.select("push", ["log/a.md"])[0]  # main pushes: always
    assert ci_select.select("pull_request", None)[0]  # git diff failed
    assert ci_select.select("pull_request", [])[0]  # nothing listed


def _dry(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def test_dry_run_docs_only_and_tools_change(tmp_path):
    """The dry run shows the selection for a docs-only and for a tools change, and writes
    the step output the workflow reads."""
    out = tmp_path / "out"
    env = {"GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin"}
    p = _dry("--event", "pull_request", "--files", "docs/superpowers/plans/p.md", env=env)
    assert p.returncode == 0 and p.stdout.startswith("sim=false:"), p.stdout
    p = _dry("--event", "pull_request", "--files", "log/a.md", "tools/xut/run.py", env=env)
    assert p.stdout.startswith("sim=true:") and "code tools/xut/run.py" in p.stdout
    assert out.read_text() == "sim=false\nsim=true\n"


def test_git_diff_failure_runs_everything(tmp_path):
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--event", "pull_request", "--base", "no-such-ref"],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # not a git repository
    )
    assert p.returncode == 0 and p.stdout.startswith("sim=true:"), p.stdout


def test_the_script_is_stdlib_only():
    """The changes job runs it with the runner's python3, before uv sync."""
    text = SCRIPT.read_text()
    assert "from xut" not in text and "import xut" not in text


def test_workflow_gates_every_sim_step_and_always_runs_the_job():
    wf = yaml.safe_load((repo_root() / ".github/workflows/ci.yml").read_text())
    jobs = wf["jobs"]
    sim = jobs["sim"]
    # the check is reported on every PR (unless cancelled), after the selection
    assert sim["needs"] == "changes" and sim["if"] == "${{ !cancelled() }}"
    assert jobs["changes"]["outputs"]["sim"] == "${{ steps.select.outputs.sim }}"
    select = next(s for s in jobs["changes"]["steps"] if s.get("id") == "select")
    assert "tools/xut/ci_select.py" in select["run"]
    checkout = jobs["changes"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0  # base...HEAD needs the history
    steps = sim["steps"]
    # fail-safe: a failed or skipped selection fails the sim check, never a green skip
    assert steps[0]["if"] == "needs.changes.result != 'success'"
    assert "exit 1" in steps[0]["run"]
    assert steps[1]["if"] == "needs.changes.outputs.sim == 'false'"  # the only skip
    assert all(s.get("if") == GATE for s in steps[2:]), [s.get("if") for s in steps]
    runs = " ".join(s.get("run", "") for s in steps[2:])
    assert "pytest" in runs and "xut run 'unit:flops'" in runs and "crosscheck" in runs
    assert "if" not in jobs["tooling"]  # the tooling job always runs in full
    assert all("if" not in s or "head_ref" in str(s) or "pull_request" in s["if"]
               for s in jobs["tooling"]["steps"])  # fmt: skip
