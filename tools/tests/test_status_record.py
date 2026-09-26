# SPDX-License-Identifier: Apache-2.0
"""``xut status record`` (spec §9, §11; Task 18): results, tree hash, reach-confirmed
coverage, open findings, and per-model-source results, on a throwaway git repository."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml
from click.testing import CliRunner

from xut.cli import main
from xut.errors import XutError
from xut.paths import repo_root
from xut.runners.base import ConfigResult, RunResult
from xut.status import (
    REFERENCE_MODEL_SOURCE,
    load_status,
    record,
    render_progress,
    tree_paths,
    validate,
)
from xut.workunits import WorkUnit

GH = "unisim-gh-2020.1"
FAMILY_DIR = "tests/7series/register"
SPDX = "# SPDX-License-Identifier: Apache-2.0\n"

_RUNNERS = {"python": "yes", "xsim": "yes", "iverilog": "yes", "verilator": "yes", "hw": "yes"}


def _test(tid: str, style: str = "vector", **extra) -> dict:
    t = {
        "id": tid,
        "level": tid.split(".")[2],
        "style": style,
        "exercises": [],
        "attr_sampling": {},
        "runners": dict(_RUNNERS),
        "flows": ["rtl", "vivado"],
        "gaps": ["fixture"],
    }
    t.update(extra)
    return t


TESTS = [
    _test(
        "7series.FDRE.L1.capture",
        exercises=["port:C", "port:D", "port:Q", "attr:INIT=1'b0"],
        runners={**_RUNNERS, "verilator": "unsupported", "hw": "no"},
        unsupported_reasons={"verilator": "x inputs", "hw": "not renderable"},
    ),
    _test("7series.FDRE.L1.ce_hold", exercises=["port:CE"]),
    _test(
        "7series.FDRE.L2.sv_r",
        style="sv",
        source="sv/tb_r.sv",
        exercises=["port:R"],
        runners={**_RUNNERS, "python": "no", "hw": "no"},
        unsupported_reasons={"python": "self-checking", "hw": "sv"},
        flows=["rtl"],
    ),
]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(root: Path, msg: str = "c") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def _result(
    root: Path,
    tid: str,
    runner: str,
    status: str,
    ms: str = REFERENCE_MODEL_SOURCE,
    *,
    reason: str | None = None,
    bins=None,
    style: str = "vector",
    configs=(),
) -> None:
    d = root / "build/rtl" / runner / ms / tid
    d.mkdir(parents=True, exist_ok=True)
    RunResult(
        tid,
        runner,
        "rtl",
        style,
        status,
        reason or (None if status == "pass" else f"{status} reason"),
        model_source=ms,
        tools={"iverilog": "12.0"} if runner == "iverilog" else {},
        container={"image": "xut-sim:1", "digest": "sha256:abc"} if runner == "iverilog" else None,
        bins_reached=bins,
        configs=[ConfigResult(c, st, None if st == "pass" else "r") for c, st in configs],
    ).write(d)


@pytest.fixture
def repo(tmp_path):
    """A committed FDRE: catalog, test.yaml, shared unit code, models and overrides."""
    root = tmp_path / "repo"
    (root / "catalog/7series").mkdir(parents=True)
    shutil.copy(repo_root() / "catalog/7series/FDRE.yaml", root / "catalog/7series/FDRE.yaml")
    (root / "catalog/7series/FDRE.overrides.yaml").write_text(SPDX + "claims: []\n")
    d = root / FAMILY_DIR / "FDRE"
    d.mkdir(parents=True)
    doc = {
        "primitive": "FDRE",
        "family": "7series",
        "work_unit": "flops",
        "doc_refs": [],
        "tests": TESTS,
    }
    (d / "test.yaml").write_text(SPDX + yaml.safe_dump(doc, sort_keys=False))
    shared = root / FAMILY_DIR / "_shared/flops"
    shared.mkdir(parents=True)
    (shared / "recipes.py").write_text(SPDX + "X = 1\n")
    models = root / "models/xut_models/7series"
    (models / "_common").mkdir(parents=True)
    (models / "fdre.py").write_text(SPDX + "M = 1\n")
    (models / "_common/flops.py").write_text(SPDX + "C = 1\n")
    (root / "docs").mkdir()
    (root / "docs/work-units.yaml").write_text(
        SPDX + "family: 7series\nunits:\n  flops: {group: register, primitives: [FDRE, FDSE]}\n"
    )
    (root / "findings").mkdir()
    (root / "findings/FDRE-sim-divergence-L1-ce_hold.md").write_text("# x\n\n- Status: open\n")
    (root / "findings/FDRE-doc-gap-L1-capture.md").write_text("# x\n\n- Status: closed\n")
    (root / "findings/FDSE-doc-gap-L1-capture.md").write_text("# x\n\n- Status: open\n")
    (root / ".gitignore").write_text("build/\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, "fixture")
    return root


def _results(root: Path, ms: str = REFERENCE_MODEL_SOURCE) -> None:
    cap, ce, sv = (t["id"] for t in TESTS)
    reached = ["port:C", "port:D", "port:Q", "attr:INIT=1'b0", "attr:INIT=1'b1"]
    _result(root, cap, "python", "pass", ms, bins=reached)
    _result(root, cap, "xsim", "pass", ms)
    _result(root, cap, "iverilog", "pass", ms)
    _result(root, ce, "python", "pass", ms, bins=["port:C"])  # CE declared, not reached
    _result(root, ce, "iverilog", "fail", ms)
    _result(root, ce, "xsim", "skip", ms, reason="runner unavailable: no Vivado")
    _result(root, sv, "iverilog", "pass", ms, style="sv")
    _result(root, sv, "xsim", "error", ms, style="sv")


def _expected_hash(root: Path) -> str:
    lines = sorted(
        f"{p} {_git(root, 'rev-parse', f'HEAD:{p}')}"
        for p in tree_paths("7series", "register", "FDRE", "flops")
        if (root / p).exists()
    )
    return "sha256:" + hashlib.sha256("".join(f"{x}\n" for x in lines).encode()).hexdigest()


def test_record_results_tree_hash_and_coverage(repo):
    _results(repo)
    warnings: list[str] = []
    s = record(repo, "FDRE", warn=warnings.append)
    assert s["results"] == {
        "L1/hw/vivado": "not-run",  # capture: n/a, ce_hold: declared, never run
        "L1/iverilog/rtl": "fail",
        "L1/iverilog/vivado": "not-run",  # declared flow, not run in step 2
        "L1/python/rtl": "pass",
        "L1/verilator/rtl": "not-run",  # not-run beats unsupported
        "L1/verilator/vivado": "not-run",
        "L1/xsim/rtl": "pass",  # unavailable is not-run, which pass beats
        "L1/xsim/vivado": "not-run",
        "L2/iverilog/rtl": "pass",
        "L2/python/rtl": "n/a",
        "L2/verilator/rtl": "not-run",
        "L2/xsim/rtl": "error",
    }
    assert "results_by_model_source" not in s
    assert not any("/hw/rtl" in k or k.startswith("L2/hw") for k in s["results"])
    assert s["measured"]["tree_hash"] == _expected_hash(repo)
    assert s["measured"]["tools"] == {"iverilog": "12.0", "container": "sha256:abc"}
    assert s["measured"]["model_sources"] == [REFERENCE_MODEL_SOURCE]
    assert s["coverage"]["covered"] == ["port:Q", "port:C", "port:D", "port:R", "attr:INIT=1'b0"]
    assert "port:CE" in s["coverage"]["uncovered"]
    assert "attr:INIT=1'b1" in s["coverage"]["uncovered"]  # reached, but not declared
    assert s["findings"] == ["FDRE-sim-divergence-L1-ce_hold"]
    assert any("7series.FDRE.L1.ce_hold" in w and "port:CE" in w for w in warnings)
    on_disk = load_status(repo / "status/7series/FDRE.yaml")
    assert on_disk == s
    assert (repo / "status/7series/FDRE.yaml").read_text().startswith(SPDX)


def test_record_keeps_notes_of_an_existing_status(repo):
    _results(repo)
    s = record(repo, "FDRE", warn=lambda m: None)
    s["notes"] = "hand-written"
    p = repo / "status/7series/FDRE.yaml"
    p.write_text(SPDX + yaml.safe_dump(s, sort_keys=False))
    assert record(repo, "FDRE", warn=lambda m: None)["notes"] == "hand-written"


@pytest.mark.parametrize(
    "path",
    [
        f"{FAMILY_DIR}/FDRE/test.yaml",
        f"{FAMILY_DIR}/_shared/flops/recipes.py",
        f"{FAMILY_DIR}/_shared/flops/new_untracked.py",
        "models/xut_models/7series/_common/flops.py",
        "models/xut_models/7series/fdre.py",
        "catalog/7series/FDRE.overrides.yaml",
    ],
)
def test_record_refuses_uncommitted_inputs(repo, path):
    _results(repo)
    p = repo / path
    p.write_text((p.read_text() if p.exists() else SPDX) + "# dirty\n")
    with pytest.raises(XutError, match="uncommitted") as e:
        record(repo, "FDRE", warn=lambda m: None)
    assert Path(path).name in str(e.value)
    assert not (repo / "status/7series/FDRE.yaml").exists()


def test_committing_a_shared_change_changes_the_tree_hash(repo):
    _results(repo)
    before = record(repo, "FDRE", warn=lambda m: None)["measured"]["tree_hash"]
    (repo / FAMILY_DIR / "_shared/flops/recipes.py").write_text(SPDX + "X = 2\n")
    _commit(repo)
    after = record(repo, "FDRE", warn=lambda m: None)["measured"]["tree_hash"]
    assert before != after and after == _expected_hash(repo)


def test_model_sources_coexist(repo):
    _results(repo, GH)
    gh = record(repo, "FDRE", model_source=GH, warn=lambda m: None)
    assert gh["results"] == {}  # the reference results are untouched (still the stub's)
    assert gh["results_by_model_source"][GH]["L1/iverilog/rtl"] == "fail"
    assert gh["measured"]["model_sources"] == [GH]
    assert "unisim" not in "".join(gh["measured"]["tools"])  # never a tools entry
    assert gh["coverage"]["covered"] == []  # coverage comes from the reference source

    _results(repo)
    _result(repo, "7series.FDRE.L1.ce_hold", "iverilog", "pass")
    both = record(repo, "FDRE", warn=lambda m: None)
    assert both["results_by_model_source"] == gh["results_by_model_source"]
    assert both["results"]["L1/iverilog/rtl"] == "pass"
    assert both["measured"]["model_sources"] == [REFERENCE_MODEL_SOURCE, GH]
    validate(gh)
    validate(both)
    assert load_status(repo / "status/7series/FDRE.yaml") == both

    again = record(repo, "FDRE", model_source=GH, warn=lambda m: None)
    assert again["results"] == both["results"]  # re-recording gh leaves 2025.2 alone


def _status(**extra) -> dict:
    s = {
        "primitive": "FDRE",
        "family": "7series",
        "work_unit": "flops",
        "model_library": "unisims",
        "measured": {"tree_hash": None, "tools": {}},
        "results": {},
        "findings": [],
        "coverage": {"covered": [], "uncovered": []},
        "notes": "",
    }
    s.update(extra)
    return s


@pytest.mark.parametrize(
    "by",
    [
        {GH: {"L1/iverilog": "pass"}},  # no flow
        {GH: {"L1/iverilog/rtl": "maybe"}},  # not a results value
        {REFERENCE_MODEL_SOURCE: {"L1/iverilog/rtl": "pass"}},  # belongs in results
    ],
)
def test_results_by_model_source_schema_rejects_bad_entries(by):
    validate(_status(results_by_model_source={GH: {"L1/iverilog/rtl": "pass"}}))
    with pytest.raises(jsonschema.ValidationError):
        validate(_status(results_by_model_source=by))


def test_record_without_any_result_is_an_error(repo):
    with pytest.raises(XutError, match="no result.json"):
        record(repo, "FDRE", model_source="unisim-typo", warn=lambda m: None)


def test_record_without_tests_is_an_error(repo):
    with pytest.raises(XutError, match="no tests for FDSE"):
        record(repo, "FDSE", warn=lambda m: None)


def test_render_progress_marks_a_gh_disagreement():
    units = {"flops": WorkUnit("flops", "7series", ("FDRE", "FDSE"), ("register",))}
    fdre = _status(
        results={"L1/iverilog/rtl": "pass", "L2/iverilog/rtl": "pass"},
        results_by_model_source={GH: {"L1/iverilog/rtl": "fail", "L2/iverilog/rtl": "pass"}},
    )
    fdse = _status(
        primitive="FDSE",
        results={"L1/iverilog/rtl": "pass"},
        results_by_model_source={GH: {"L1/iverilog/rtl": "not-run"}},
    )
    out = render_progress([fdre, fdse], units)
    row = next(line for line in out.splitlines() if line.startswith("| FDRE "))
    cells = [c.strip() for c in row.split("|")[4:8]]
    assert cells[1].endswith("+gh") and "✓" in cells[1]  # the reference mark, flagged
    assert not cells[2].endswith("+gh")  # agreement
    row = next(line for line in out.splitlines() if line.startswith("| FDSE "))
    assert "+gh" not in row  # not-run is no disagreement


def test_cli_status_record(repo, monkeypatch):
    _results(repo)
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: repo)
    r = CliRunner().invoke(main, ["status", "record", "--unit", "flops"])
    assert r.exit_code == 0, r.output
    assert "skipped FDSE: no tests yet" in r.output
    assert "wrote status/7series/FDRE.yaml (unisim-2025.2)" in r.output
    assert "warning: 7series.FDRE.L1.ce_hold: declares port:CE" in r.output
    r = CliRunner().invoke(main, ["status", "record", "FDRE", "--unit", "flops"])
    assert r.exit_code != 0 and "either PRIM... or --unit" in r.output
    r = CliRunner().invoke(main, ["status", "record", "--unit", "nosuch"])
    assert r.exit_code == 1 and "unknown work unit" in r.output
    (repo / FAMILY_DIR / "_shared/flops/recipes.py").write_text(SPDX + "# dirty\n")
    r = CliRunner().invoke(main, ["status", "record", "FDRE"])
    assert r.exit_code == 1 and "Error: refusing to record" in r.output
    assert "recipes.py" in r.output


def test_record_covers_declared_crosses_from_passing_configurations(repo):
    """Ruling S19: a cross bin is covered when a configuration that ran and passed (on
    the golden model for a vector test, on a simulator for sv) has those values; an
    attribute a configuration does not set takes its catalog default."""
    (repo / "catalog/7series/FDRE.overrides.yaml").write_text(
        SPDX + "claims: []\ncrosses: [[INIT, IS_C_INVERTED]]\n"
    )
    doc = yaml.safe_load((repo / FAMILY_DIR / "FDRE/test.yaml").read_text())
    cap, _, sv = doc["tests"]
    cap["exercises"] += ["cross:INIT=1'b1,IS_C_INVERTED=1'b0", "cross:INIT=1'b1,IS_C_INVERTED=1'b1"]
    sv["exercises"] += ["cross:INIT=1'b0,IS_C_INVERTED=1'b1"]
    sv["configs"] = [{"cfg": "inv", "attrs": {"IS_C_INVERTED": 1}}, {"cfg": "bad", "attrs": {}}]
    (repo / FAMILY_DIR / "FDRE/test.yaml").write_text(SPDX + yaml.safe_dump(doc, sort_keys=False))
    _commit(repo)
    _results(repo)
    for cfg, attrs in (("a", "attr.INIT=1'b1"), ("b", "attr.INIT=1'b1 attr.IS_C_INVERTED=1'b1")):
        d = repo / "build/rtl/python" / REFERENCE_MODEL_SOURCE / cap["id"] / f"cfg-{cfg}"
        d.mkdir(parents=True)
        (d / "stim.xvec").write_text(
            f"# xut-vec 2  prim=FDRE cfg={cfg} nin=3 nout=1 nclk=1 settle_ps=1 seed=0 {attrs}\n"
        )
    _result(
        repo, cap["id"], "python", "pass", bins=["port:C"], configs=[("a", "pass"), ("b", "error")]
    )
    _result(
        repo, sv["id"], "iverilog", "fail", style="sv", configs=[("inv", "pass"), ("bad", "fail")]
    )
    warnings: list[str] = []
    s = record(repo, "FDRE", warn=warnings.append)
    crosses = [b for b in s["coverage"]["covered"] if b.startswith("cross:")]
    assert crosses == ["cross:INIT=1'b0,IS_C_INVERTED=1'b1", "cross:INIT=1'b1,IS_C_INVERTED=1'b0"]
    assert "cross:INIT=1'b1,IS_C_INVERTED=1'b1" in s["coverage"]["uncovered"]  # cfg b errored
    assert any("cross:INIT=1'b1,IS_C_INVERTED=1'b1" in w for w in warnings)
