# SPDX-License-Identifier: Apache-2.0
"""``xut status record`` (spec §9, §11; Task 18): results, tree hash, reach-confirmed
coverage, open findings, and per-model-source results, on a throwaway git repository."""

import hashlib
import json
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
from xut.provenance import tree_state
from xut.runners.base import ConfigResult, RunResult
from xut.status import (
    REFERENCE_MODEL_SOURCE,
    StaleResultError,
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
    tree_hash: str | None = "current",
    dirty: bool | None = False,
    tools: dict | None = None,
) -> None:
    """A result.json as `xut run` writes it, stamped with the CURRENT tree hash (or
    ``tree_hash``/``dirty`` as given)."""
    d = root / "build/rtl" / runner / ms / tid
    d.mkdir(parents=True, exist_ok=True)
    if tree_hash == "current":
        tree_hash = tree_state(root, tree_paths("7series", "register", "FDRE", "flops")).tree_hash
    RunResult(
        tid,
        runner,
        "rtl",
        style,
        status,
        reason or (None if status == "pass" else f"{status} reason"),
        model_source=ms,
        tools=tools if tools is not None else {"iverilog": "12.0"} if runner == "iverilog" else {},
        container={"image": "xut-sim:1", "digest": "sha256:abc"} if runner == "iverilog" else None,
        bins_reached=bins,
        configs=[ConfigResult(c, st, None if st == "pass" else "r") for c, st in configs],
        tree_hash=tree_hash,
        head="abc",
        dirty=dirty,
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
    _result(root, ce, "verilator", "pass", ms)
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
        "L1/verilator/rtl": "pass",  # capture: unsupported; ce_hold: pass (pass > unsupported)
        "L1/verilator/vivado": "not-run",
        "L1/xsim/rtl": "not-run",  # ce_hold unavailable: not-run outranks pass (S22)
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
    assert s["measured"]["tools_by_model_source"] == {
        REFERENCE_MODEL_SOURCE: s["measured"]["tools"]
    }
    assert s["measured"]["tree_hash_by_model_source"] == {
        REFERENCE_MODEL_SOURCE: s["measured"]["tree_hash"]
    }
    assert s["measured"]["model_sources"] == [REFERENCE_MODEL_SOURCE]
    assert s["coverage"]["covered"] == ["port:Q", "port:C", "port:D", "port:R", "attr:INIT=1'b0"]
    assert "port:CE" in s["coverage"]["uncovered"]
    assert "attr:INIT=1'b1" in s["coverage"]["uncovered"]  # reached, but not declared
    assert s["findings"] == ["FDRE-sim-divergence-L1-ce_hold"]
    assert any("7series.FDRE.L1.ce_hold" in w and "port:CE" in w for w in warnings)
    on_disk = load_status(repo / "status/7series/FDRE.yaml")
    assert on_disk == s
    assert (repo / "status/7series/FDRE.yaml").read_text().startswith(SPDX)


def test_tools_are_replaced_on_each_record(repo):
    _results(repo)
    cap = TESTS[0]["id"]
    _result(repo, cap, "xsim", "pass", tools={"xsim": "2025.2"})
    assert record(repo, "FDRE", warn=lambda m: None)["measured"]["tools"]["xsim"] == "2025.2"
    _result(repo, cap, "xsim", "pass")
    tools = record(repo, "FDRE", warn=lambda m: None)["measured"]["tools"]
    assert "xsim" not in tools and tools["iverilog"] == "12.0"


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


@pytest.mark.parametrize(
    "path",
    [
        "tests/7series/register/FDRE/README.md",
        "tests/7series/register/_shared/flops/recipes.py",
        "models/xut_models/7series/fdre.py",
        "models/xut_models/7series/_common/flops.py",
        "catalog/7series/FDRE.overrides.yaml",
    ],
)
def test_committing_a_change_to_any_input_changes_the_tree_hash(repo, path):
    """Each of the 5 path kinds of tree_paths feeds the hash. Results measured before
    the commit are stale: record refuses them until `xut run` re-stamps them."""
    _results(repo)
    before = record(repo, "FDRE", warn=lambda m: None)["measured"]["tree_hash"]
    p = repo / path
    p.write_text((p.read_text() if p.exists() else SPDX) + "# changed\n")
    _commit(repo)
    with pytest.raises(StaleResultError, match="not measured at the current tree"):
        record(repo, "FDRE", warn=lambda m: None)
    _results(repo)  # re-run: stamped with the new tree hash
    after = record(repo, "FDRE", warn=lambda m: None)["measured"]["tree_hash"]
    assert before != after and after == _expected_hash(repo)


@pytest.mark.parametrize(
    ("tree_hash", "dirty"),
    [("sha256:" + "0" * 64, False), ("current", True), (None, None), ("current", None)],
)
def test_record_refuses_stale_or_dirty_results(repo, tree_hash, dirty):
    _results(repo)
    _result(repo, TESTS[1]["id"], "iverilog", "fail", tree_hash=tree_hash, dirty=dirty)
    with pytest.raises(StaleResultError) as e:
        record(repo, "FDRE", warn=lambda m: None)
    assert "rtl/iverilog/7series.FDRE.L1.ce_hold" in str(e.value)
    assert f"dirty {dirty}" in str(e.value)


def test_vector_bins_need_a_simulator_pass(repo):
    """Ruling S21: the golden model's reach alone covers nothing; a simulator must also
    have passed the vector test against the reference source."""
    _results(repo)
    cap = TESTS[0]["id"]
    _result(repo, cap, "xsim", "fail")
    _result(repo, cap, "iverilog", "error")
    warnings: list[str] = []
    s = record(repo, "FDRE", warn=warnings.append)
    assert s["coverage"]["covered"] == ["port:R"]  # only the sv test's
    assert any(cap in w and "no simulator passed" in w for w in warnings)


def test_model_sources_coexist(repo):
    _results(repo, GH)
    gh = record(repo, "FDRE", model_source=GH, warn=lambda m: None)
    assert gh["results"] == {}  # the reference results are untouched (still the stub's)
    assert gh["results_by_model_source"][GH]["L1/iverilog/rtl"] == "fail"
    assert gh["measured"]["model_sources"] == [GH]
    assert gh["measured"]["tree_hash"] is None  # the reference's: not recorded yet
    assert gh["measured"]["tools"] == {}
    assert gh["measured"]["tools_by_model_source"][GH]["iverilog"] == "12.0"
    assert "unisim" not in "".join(gh["measured"]["tools_by_model_source"][GH])
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


def test_each_source_keeps_its_own_tree_hash_and_tools(repo):
    """Ruling S21: recording one source never changes another's hash or tools; a
    source recorded at another tree shows as stale (~gh) in PROGRESS.md, uncompared."""
    _results(repo, GH)
    old = record(repo, "FDRE", model_source=GH, warn=lambda m: None)["measured"]
    (repo / "models/xut_models/7series/fdre.py").write_text(SPDX + "M = 2\n")
    _commit(repo)
    _results(repo)
    warnings: list[str] = []
    s = record(repo, "FDRE", warn=warnings.append)
    m = s["measured"]
    assert m["tree_hash_by_model_source"][GH] == old["tree_hash_by_model_source"][GH]
    assert m["tree_hash_by_model_source"][REFERENCE_MODEL_SOURCE] == m["tree_hash"]
    assert m["tree_hash"] != old["tree_hash_by_model_source"][GH]
    assert m["tools_by_model_source"][GH] == old["tools_by_model_source"][GH]
    assert any(f"{GH} was recorded at tree hash" in w for w in warnings)
    units = {"flops": WorkUnit("flops", "7series", ("FDRE",), ("register",))}
    row = next(ln for ln in render_progress([s], units).splitlines() if ln.startswith("| FDRE"))
    assert "~gh" in row and "+gh" not in row


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
    assert "; coverage 5/20" in r.output
    assert "warning: 7series.FDRE.L1.ce_hold: declares port:CE" in r.output
    _results(repo, GH)
    r = CliRunner().invoke(main, ["status", "record", "FDRE", "--model-source", GH])
    assert r.exit_code == 0, r.output
    assert f"wrote status/7series/FDRE.yaml ({GH})" in r.output and "coverage" not in r.output
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


def test_status_init_refresh_bins_only_touches_never_recorded_stubs(repo, monkeypatch):
    """Ruling S20: `xut status init --refresh-bins` rewrites a never-recorded stub's bins
    to the current coverage_bins; a recorded status file stays byte-identical."""
    from xut.catalog.model import load_entry
    from xut.status import coverage_bins, dump_stub

    shutil.copy(repo_root() / "catalog/7series/FDSE.yaml", repo / "catalog/7series/FDSE.yaml")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: repo)
    out = repo / "status/7series"
    out.mkdir(parents=True)
    for prim in ("FDRE", "FDSE"):
        entry = load_entry("7series", prim, repo)
        stale = yaml.safe_load(dump_stub(entry, "flops"))
        stale["coverage"]["uncovered"] = [
            b for b in stale["coverage"]["uncovered"] if b.count(":") == 1
        ]  # a pre-S19 stub
        if prim == "FDSE":
            stale["measured"]["tree_hash_by_model_source"] = {GH: "sha256:" + "1" * 64}
        (out / f"{prim}.yaml").write_text(SPDX + yaml.safe_dump(stale, sort_keys=False))
    recorded_before = (out / "FDSE.yaml").read_bytes()

    r = CliRunner().invoke(main, ["status", "init"])
    assert r.exit_code == 0 and "refreshed" not in r.output
    assert "port:C:edge" not in (out / "FDRE.yaml").read_text()  # plain init: untouched

    r = CliRunner().invoke(main, ["status", "init", "--refresh-bins"])
    assert r.exit_code == 0, r.output
    assert "refreshed the bins of 1 never-recorded stub(s)" in r.output
    fdre = load_status(out / "FDRE.yaml")
    assert fdre["coverage"] == {
        "covered": [],
        "uncovered": coverage_bins(load_entry("7series", "FDRE", repo)),
    }
    assert (out / "FDSE.yaml").read_bytes() == recorded_before  # recorded: byte-identical
    r = CliRunner().invoke(main, ["status", "init", "--refresh-bins"])
    assert "refreshed the bins of 0 never-recorded stub(s)" in r.output  # idempotent


def test_xut_run_stamps_tree_provenance(repo, monkeypatch):
    """Ruling S21: every result.json carries the primitive's tree_hash, head and dirty."""
    from xut.modelsrc import ModelSource

    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: repo)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ModelSource("ms", repo))
    args = ["run", "FDRE", "--runner", "python", "--style", "sv"]  # a declared skip
    r = CliRunner().invoke(main, args)
    assert r.exit_code == 0, r.output
    res = repo / f"build/rtl/python/ms/{TESTS[2]['id']}/result.json"
    data = json.loads(res.read_text())
    assert data["status"] == "skip"
    assert data["tree_hash"] == _expected_hash(repo) and data["dirty"] is False
    assert data["head"] == _git(repo, "rev-parse", "HEAD")
    (repo / FAMILY_DIR / "_shared/flops/recipes.py").write_text(SPDX + "X = 3\n")
    CliRunner().invoke(main, args)
    assert json.loads(res.read_text())["dirty"] is True


@pytest.mark.parametrize(
    ("values", "worst"),
    [
        (["pass", "not-run"], "not-run"),  # S22: an unrun declared test is never hidden
        (["pass", "skip"], "pass"),  # a skip is deliberate and reasoned
        (["skip", "unsupported", "n/a"], "skip"),
        (["not-run", "error"], "error"),
        (["error", "fail"], "fail"),
        (["unsupported", "n/a"], "unsupported"),
    ],
)
def test_worst_result_precedence(values, worst):
    from xut.status import RECORD_PRECEDENCE, worst_result

    assert RECORD_PRECEDENCE == ("fail", "error", "not-run", "pass", "skip", "unsupported", "n/a")
    assert worst_result(values) == worst
