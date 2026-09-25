# SPDX-License-Identifier: Apache-2.0
"""`xut run`: selection (selectors, repeatable --level/--style/--runner) and exit codes."""

import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from xut.cli import main
from xut.modelsrc import ModelSource
from xut.runners.base import RunResult

FIX = Path(__file__).parent / "fixtures"


def _entry(tid: str, style: str = "vector") -> dict:
    return {
        "id": tid,
        "level": tid.split(".")[2],
        "style": style,
        "exercises": [],
        "attr_sampling": {},
        "runners": {"python": "yes"},
        "flows": ["rtl"],
    }


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo with TOYFF L0/L1/L2 vector tests and an L1 sv test; run_tests recorded."""
    d = tmp_path / "tests/7series/register/TOYFF"
    d.mkdir(parents=True)
    doc = {
        "primitive": "TOYFF",
        "family": "7series",
        "work_unit": "toy",
        "doc_refs": [],
        "tests": [
            _entry("7series.TOYFF.L0.a"),
            _entry("7series.TOYFF.L1.b"),
            _entry("7series.TOYFF.L2.c"),
            _entry("7series.TOYFF.L1.d", style="sv"),
        ],
    }
    (d / "test.yaml").write_text(yaml.safe_dump(doc))
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(
        "xut.modelsrc.resolve", lambda name="auto": ModelSource("unisim-test", tmp_path)
    )
    calls = []

    def fake_run_tests(cases, runners, ctx):
        calls.append(([c.id for c in cases], list(runners), ctx))
        return [RunResult(c.id, r, ctx.flow, c.style, "pass") for c in cases for r in runners]

    monkeypatch.setattr("xut.run.run_tests", fake_run_tests)
    return calls


def _run(*args):
    return CliRunner().invoke(main, ["run", *args])


def test_repeatable_levels(repo):
    r = _run("--level", "L0", "--level", "L1", "--style", "vector")
    assert r.exit_code == 0, r.output
    assert repo[0][0] == ["7series.TOYFF.L0.a", "7series.TOYFF.L1.b"]


def test_repeatable_styles(repo):
    r = _run("--style", "vector", "--style", "sv", "--level", "L1")
    assert r.exit_code == 0, r.output
    assert repo[0][0] == ["7series.TOYFF.L1.b", "7series.TOYFF.L1.d"]


def test_selectors_and_runner_default(repo):
    r = _run("7series.TOYFF.L2.*", "--seed", "5", "--jobs", "3", "--timeout", "9")
    assert r.exit_code == 0, r.output
    ids, runners, ctx = repo[0]
    assert ids == ["7series.TOYFF.L2.c"]
    assert runners == ["python", "xsim", "iverilog"]  # every RUNNERS entry but iverilog-vz
    assert (ctx.seed, ctx.jobs, ctx.timeout_s, ctx.flow) == (5, 3, 9, "rtl")
    assert ctx.model_source.name == "unisim-test"
    assert "7series.TOYFF.L2.c" in r.output and "pass" in r.output


def test_nothing_selected_is_exit_0_with_message(repo):
    r = _run("NOSUCH", "--level", "L3")
    assert r.exit_code == 0, r.output
    assert "no tests selected" in r.output and "NOSUCH" in r.output and "L3" in r.output
    assert repo == []


def test_unknown_runner_is_clean_error(repo):
    r = _run("--runner", "nosuch")
    assert r.exit_code != 0
    assert "nosuch" in r.output and "Traceback" not in r.output


def test_verilator_adds_iverilog_vz(repo, monkeypatch):
    from xut.runners import RUNNERS
    from xut.runners.python import PythonRunner

    monkeypatch.setitem(RUNNERS, "verilator", PythonRunner)
    monkeypatch.setitem(RUNNERS, "iverilog-vz", PythonRunner)
    assert _run("--runner", "verilator").exit_code == 0
    assert repo[0][1] == ["verilator", "iverilog-vz"]
    assert _run().exit_code == 0  # default: everything but iverilog-vz, then added back
    assert repo[1][1] == ["python", "xsim", "iverilog", "verilator", "iverilog-vz"]


def test_fail_or_error_exits_1(repo, monkeypatch):
    monkeypatch.setattr(
        "xut.run.run_tests",
        lambda cases, runners, ctx: [
            RunResult(cases[0].id, "python", "rtl", "vector", "error", "boom")
        ],
    )
    r = _run("7series.TOYFF.L0.a")
    assert r.exit_code == 1
    assert "error" in r.output


def test_end_to_end_python_on_fixture(tmp_path, monkeypatch):
    """The real run_tests on the TOYFF fixture (toy catalog entry and model)."""
    from test_runner_base import TOY_ENTRY, ToyDff

    shutil.copytree(FIX / "tests", tmp_path / "tests")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(
        "xut.modelsrc.resolve", lambda name="auto": ModelSource("unisim-test", tmp_path)
    )
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: TOY_ENTRY)
    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: ToyDff)
    r = _run("TOYFF", "--runner", "python")
    assert r.exit_code == 0, r.output
    # two vector tests run python; the sv and cocotb tests get declared-unsupported skips
    assert "progress: done=4 total=4" in r.output
    res = tmp_path / "build/rtl/python/unisim-test/7series.TOYFF.L1.capture/result.json"
    assert res.is_file()
    assert (tmp_path / "build/rtl/summary.json").is_file()


def test_selector_matching_nothing_warns(repo):
    r = CliRunner().invoke(main, ["run", "TOYFF", "NOSUCH"])
    assert r.exit_code == 0, r.output
    assert "warning: selector 'NOSUCH' matched no test" in r.output
    assert "warning: selector 'TOYFF'" not in r.output


def test_keyboard_interrupt_exits_130(repo, monkeypatch):
    def interrupted(cases, runners, ctx):
        raise KeyboardInterrupt

    monkeypatch.setattr("xut.run.run_tests", interrupted)
    r = _run("TOYFF")
    assert r.exit_code == 130
    assert "interrupted" in r.output
