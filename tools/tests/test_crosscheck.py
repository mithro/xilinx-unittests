# SPDX-License-Identifier: Apache-2.0
"""``xut crosscheck``: gathering, the spec §8 finding classes, matrix, finding stubs, CLI.

Each classification rule is pinned with synthetic ``View``s; ``gather`` and the CLI run
on a synthetic ``build/`` tree written here (result.json + trace.xtr per runner)."""

import copy
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from xut import crosscheck as xc
from xut.cli import main
from xut.crosscheck import FINDING_CLASSES, X_OBSERVABLE, Finding, View, classify
from xut.formats import xtr

TID = "7series.TOYFF.L1.capture"


def T(samples: dict, prov: dict | None = None, kind: str = "actual") -> xtr.Trace:
    """A trace: ``{label: {port: bits}}``; ``prov`` = ``{label: {port: token}}``."""
    t = xtr.Trace({"runner": "r", "kind": kind})
    for label, ports in samples.items():
        t.add(label, ports, (prov or {}).get(label))
    return t


def EXP(samples: dict, prov: str = "doc:1") -> xtr.Trace:
    """An expected trace with one provenance token for every port of every sample."""
    return T(samples, {lbl: dict.fromkeys(p, prov) for lbl, p in samples.items()}, "expected")


def V(runner, trace=None, flow="rtl", ms="ms1", status="pass", **result) -> View:
    return View(flow, runner, status, ms, trace, dict(result))


def views(*vs: View) -> dict:
    return {(v.flow, v.runner): v for v in vs}


def classes(fs: list[Finding]) -> list[str]:
    return [f.cls for f in fs]


Q0 = {"c/S1": {"Q": "0"}, "c/S2": {"Q": "1"}}
Q1 = {"c/S1": {"Q": "1"}, "c/S2": {"Q": "1"}}


# --- constants ---------------------------------------------------------------------------


def test_finding_classes_are_the_spec_table_in_order():
    assert FINDING_CLASSES == (
        "doc-vs-model",
        "doc-gap",
        "sim-divergence",
        "x-dependence",
        "transform-bug",
        "flow-mismatch",
        "silicon-mismatch",
        "nondeterminism",
        "harness-error",
        "known-divergence",
    )


def test_x_observable():
    assert X_OBSERVABLE == {
        "python": True,
        "xsim": True,
        "iverilog": True,
        "iverilog-vz": True,
        "verilator": False,
        "hw": False,
    }


def test_slug():
    f = Finding("doc-gap", "7series.FDRE.L1.gsr_init", "rtl", "m", ("iverilog",), ())
    assert f.slug == "doc-gap-L1-gsr_init"
    f = Finding("doc-gap", "7series.FDRE.L1.a.b", "rtl", "m", ("iverilog",), ())
    assert f.slug == "doc-gap-L1-a-b"


# --- classification ------------------------------------------------------------------------


def test_agreement_is_no_finding():
    vs = views(V("python", EXP(Q0)), V("iverilog", T(Q0)), V("xsim", T(Q0)), V("verilator", T(Q0)))
    assert classify(TID, vs) == []


def test_sim_divergence():
    vs = views(V("iverilog", T(Q0)), V("xsim", T(Q1)))
    (f,) = classify(TID, vs)
    assert (f.cls, f.runners, f.flow, f.model_source) == (
        "sim-divergence",
        ("iverilog", "xsim"),
        "rtl",
        "ms1",
    )
    assert f.points == ("iverilog vs xsim: c/S1 Q[0]: expected 0, got 1 [value]",)
    assert not f.expected and f.known_of is None and f.finding is None


def test_sim_divergence_point_is_not_also_a_doc_finding():
    vs = views(V("python", EXP(Q0)), V("iverilog", T(Q1)), V("xsim", T(Q0)), V("verilator", T(Q1)))
    fs = classify(TID, vs)
    assert classes(fs) == ["sim-divergence"]
    assert len(fs[0].points) == 2  # iverilog vs xsim, verilator vs xsim


def test_sim_divergence_is_x_aware():
    """A 2-state runner cannot see x: iverilog x vs verilator 0 is not a divergence."""
    x = {"c/S1": {"Q": "x"}}
    assert classify(TID, views(V("iverilog", T(x)), V("verilator", T({"c/S1": {"Q": "0"}})))) == []
    assert classes(
        classify(TID, views(V("iverilog", T(x)), V("xsim", T({"c/S1": {"Q": "0"}}))))
    ) == ["sim-divergence"]


def test_doc_vs_model():
    vs = views(V("python", EXP(Q0, "doc:375")), V("iverilog", T(Q1)), V("xsim", T(Q1)))
    (f,) = classify(TID, vs)
    assert (f.cls, f.runners) == ("doc-vs-model", ("iverilog", "xsim"))
    assert f.points == ("c/S1 Q[0]: expected 0, got 1 (doc:375)",)


def test_doc_gap():
    vs = views(V("python", EXP(Q0, "inferred:silent")), V("iverilog", T(Q1)), V("xsim", T(Q1)))
    (f,) = classify(TID, vs)
    assert (f.cls, f.points) == ("doc-gap", ("c/S1 Q[0]: expected 0, got 1 (inferred:silent)",))


def test_doc_points_are_in_simulated_time_order():
    exp = EXP({"c/start": {"Q": "0"}, "c/S2": {"Q": "0"}, "c/S10": {"Q": "0"}})
    got = T({"c/start": {"Q": "1"}, "c/S2": {"Q": "1"}, "c/S10": {"Q": "1"}})
    (f,) = classify(TID, views(V("python", exp), V("iverilog", got)))
    assert [p.split(" ")[0] for p in f.points] == ["c/start", "c/S2", "c/S10"]


def test_one_simulator_is_every_available_simulator():
    (f,) = classify(TID, views(V("python", EXP(Q0)), V("iverilog", T(Q1))))
    assert (f.cls, f.runners) == ("doc-vs-model", ("iverilog",))


def test_per_bit_provenance_decides_doc_vs_gap():
    """Per-bit tokens are comma-joined LSB first (``golden.bit_prov``)."""
    exp = T({"c/S1": {"Q": "00"}}, {"c/S1": {"Q": "doc:1,inferred:why"}}, "expected")
    got = T({"c/S1": {"Q": "11"}})
    fs = classify(TID, views(V("python", exp), V("iverilog", got), V("xsim", got)))
    assert {f.cls: f.points for f in fs} == {
        "doc-vs-model": ("c/S1 Q[0]: expected 0, got 1 (doc:1)",),
        "doc-gap": ("c/S1 Q[1]: expected 0, got 1 (inferred:why)",),
    }


def test_expected_x_is_not_compared_on_a_two_state_runner():
    exp = EXP({"c/S1": {"Q": "x"}})
    assert classify(TID, views(V("python", exp), V("verilator", T({"c/S1": {"Q": "1"}})))) == []


def test_dont_care_bits_are_never_compared():
    exp = EXP({"c/S1": {"Q": "-"}})
    assert classify(TID, views(V("python", exp), V("iverilog", T({"c/S1": {"Q": "1"}})))) == []


def test_golden_disagreeing_with_only_some_observers_is_never_dropped():
    """golden 1; iverilog x; verilator 1. The sims do not diverge (verilator cannot see
    x), and not every sim disagrees with the golden: reported as sim-divergence."""
    vs = views(
        V("python", EXP({"c/S1": {"Q": "1"}})),
        V("iverilog", T({"c/S1": {"Q": "x"}})),
        V("verilator", T({"c/S1": {"Q": "1"}})),
    )
    (f,) = classify(TID, vs)
    assert f.cls == "sim-divergence" and f.runners == ("iverilog", "verilator")
    assert "python vs iverilog only" in f.points[0]


def test_structural_golden_disagreement_is_an_issue_not_a_doc_finding():
    issues: list[str] = []
    vs = views(V("python", EXP(Q0)), V("iverilog", T({"c/S1": {"Q": "0"}})))
    assert classify(TID, vs, issues=issues) == []
    assert issues and "missing-sample" in issues[0] and "c/S2" in issues[0]


def test_x_dependence():
    v = V("verilator", T(Q0), x_dependence=True, seeds={"stimulus": 1, "x": [3, 4]})
    (f,) = classify(TID, views(v))
    assert (f.cls, f.runners, f.points) == (
        "x-dependence",
        ("verilator",),
        ("X seeds [3, 4] disagree",),
    )


def test_transform_bug():
    (f,) = classify(TID, views(V("iverilog", T(Q0)), V("iverilog-vz", T(Q1))))
    assert (f.cls, f.runners) == ("transform-bug", ("iverilog", "iverilog-vz"))
    assert f.points == ("c/S1 Q[0]: expected 0, got 1 [value]",)


def test_iverilog_vz_is_not_a_unisim_simulator_for_doc_classes():
    vs = views(V("python", EXP(Q0)), V("iverilog", T(Q0)), V("iverilog-vz", T(Q0)))
    assert classify(TID, vs) == []


def test_flow_mismatch():
    vs = views(V("iverilog", T(Q0)), V("iverilog", T(Q1), flow="vivado"))
    (f,) = classify(TID, vs)
    assert (f.cls, f.flow, f.runners) == ("flow-mismatch", "vivado", ("iverilog",))


def test_silicon_mismatch_compares_two_state():
    exp = EXP({"c/S1": {"Q": "x"}, "c/S2": {"Q": "1"}})
    hw = T({"c/S1": {"Q": "0"}, "c/S2": {"Q": "0"}})
    (f,) = classify(TID, views(V("python", exp), V("hw", hw, flow="vivado")))
    assert (f.cls, f.flow, f.runners, f.model_source) == (
        "silicon-mismatch",
        "vivado",
        ("hw",),
        None,
    )
    assert f.points == ("c/S2 Q[0]: expected 1, got 0 (doc:1)",)


def test_nondeterminism():
    v = V("hw", T(Q0), flow="vivado", hw={"repeats_differ": True, "repeats": 5})
    (f,) = classify(TID, views(V("python", EXP(Q0)), v))
    assert (f.cls, f.points) == ("nondeterminism", ("5 runs disagree",))


def test_harness_error_suppresses_the_hw_comparison():
    v = V("hw", T(Q1), flow="vivado", hw={"selftest": "fail", "repeats_differ": True})
    (f,) = classify(TID, views(V("python", EXP(Q0)), v))
    assert (f.cls, f.points) == ("harness-error", ("self-test failed",))


# --- known divergences: never masked --------------------------------------------------------

ED = {
    "finding": "findings/TOYFF-doc-gap-L1-capture.md",
    "cls": "doc-gap",
    "runners": ["iverilog", "xsim"],
}


def test_expected_divergence_is_reported_as_known_divergence():
    exp = EXP(Q0, "inferred:silent")
    vs = views(V("python", exp), V("iverilog", T(Q1)), V("xsim", T(Q1)))
    before = copy.deepcopy(exp.samples)
    (f,) = classify(TID, vs, (ED,))
    assert (f.cls, f.known_of, f.finding, f.expected) == (
        "known-divergence",
        "doc-gap",
        "TOYFF-doc-gap-L1-capture",
        True,
    )
    assert f.points == ("c/S1 Q[0]: expected 0, got 1 (inferred:silent)",)
    # expected bits stay defined: nothing becomes '-'
    assert exp.samples == before and "-" not in "".join(p["Q"] for p in exp.samples.values())


def test_expected_divergence_must_cover_every_runner_and_the_class():
    vs = views(V("python", EXP(Q0, "inferred:x")), V("iverilog", T(Q1)), V("xsim", T(Q1)))
    assert classes(classify(TID, vs, ({**ED, "runners": ["iverilog"]},))) == ["doc-gap"]
    assert classes(classify(TID, vs, ({**ED, "cls": "doc-vs-model"},))) == ["doc-gap"]


# --- configurations that did not run are never compared (and never agreement) ------------


def test_errored_configuration_is_excluded_from_comparison():
    exp = EXP({"a/S1": {"Q": "0"}, "b/S1": {"Q": "0"}})
    py = V("python", exp, configs=[{"cfg": "a", "status": "pass"}, {"cfg": "b", "status": "pass"}])
    iv = V(
        "iverilog",
        T({"a/S1": {"Q": "0"}}),
        status="error",
        configs=[{"cfg": "a", "status": "pass"}, {"cfg": "b", "status": "error", "reason": "boom"}],
    )
    issues: list[str] = []
    assert classify(TID, views(py, iv), issues=issues) == []
    assert issues == []  # errors are reported by `check`, from the results


# --- gather / check / matrix on a build tree ------------------------------------------------


#: The tree hash every fixture result is stamped with (``xut run`` stamps the real one).
TH = "sha256:" + "a" * 64


def _cfg_entry(c: dict) -> dict:
    """A schema-complete ``configs`` entry (a non-pass needs a reason)."""
    reason = c.get("reason") or (None if c["status"] == "pass" else f"{c['status']} reason")
    return {
        "stimulus_sha256": None,
        "trace_sha256": None,
        "mismatches": 0,
        **c,
        "reason": reason,
    }


def _result(root: Path, flow, runner, ms, tid, status="pass", trace=None, reason=None, **kw):
    """A schema-valid result.json (as ``xut run`` writes it, stamped with ``TH`` on a
    clean tree unless ``tree_hash``/``dirty`` are given), plus trace.xtr if given."""
    d = root / "build" / flow / runner / ms / tid
    d.mkdir(parents=True)
    cfgs = kw.pop("configs", None)
    if cfgs is None and trace is not None:
        cfgs = sorted({lbl.split("/", 1)[0] for lbl in trace.samples})
        cfgs = [{"cfg": c, "status": status, "reason": reason} for c in cfgs]
    if reason is None and status != "pass":
        reason = f"{status} reason"
    data = {
        "format": "xut-result 1",
        "test_id": tid,
        "runner": runner,
        "flow": flow,
        "style": "vector",
        "status": status,
        "reason": reason,
        "configs": [_cfg_entry(c) for c in cfgs or []],
        "model_source": ms,
        "seeds": {"stimulus": 1, "x": []},
        "defines": {},
        "tools": {},
        "container": None,
        "duration_s": 0.0,
        "started": "",
        "host": "h",
        "x_dependence": None,
        "bins_reached": None,
        "hw": None,
        "tree_hash": TH,
        "head": "abc",
        "dirty": False,
        **kw,
    }
    (d / "result.json").write_text(json.dumps(data))
    if trace is not None:
        xtr.dump(trace, d / "trace.xtr")
    return d


def _test_yaml(root: Path, expected_divergence=(), runners=None) -> None:
    d = root / "tests/7series/register/TOYFF"
    d.mkdir(parents=True, exist_ok=True)
    t = {
        "id": TID,
        "level": "L1",
        "style": "vector",
        "exercises": [],
        "attr_sampling": {},
        "runners": runners or {"python": "yes", "iverilog": "yes", "xsim": "yes"},
        "flows": ["rtl"],
        "gaps": [],
    }
    if expected_divergence:
        t["expected_divergence"] = list(expected_divergence)
    doc = {
        "primitive": "TOYFF",
        "family": "7series",
        "work_unit": "toy",
        "doc_refs": [],
        "tests": [t],
    }
    (d / "test.yaml").write_text(yaml.safe_dump(doc))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    return tmp_path


def _xc(*args):
    return CliRunner().invoke(main, ["crosscheck", *args])


def test_gather_keys_by_model_source(repo):
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    _result(repo, "rtl", "iverilog", "ms2", TID, trace=T(Q1))
    _result(repo, "rtl", "xsim", "ms2", TID, status="skip", reason="runner unavailable: x")
    _result(repo, "rtl", "iverilog", "ms1", "7series.TOYFF.L1.other", trace=T(Q0))
    g = xc.gather(repo, TID)
    assert set(g) == {"ms1", "ms2"}
    assert set(g["ms1"]) == {("rtl", "python"), ("rtl", "iverilog")}
    assert g["ms2"][("rtl", "xsim")].trace is None
    assert g["ms2"][("rtl", "xsim")].status == "skip"
    assert g["ms1"][("rtl", "iverilog")].trace.samples == Q0


def test_two_model_sources_are_never_cross_compared(repo):
    """ms1 iverilog Q=0 and ms2 xsim Q=1 would diverge if compared; they never are."""
    _test_yaml(repo)
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    _result(repo, "rtl", "xsim", "ms2", TID, trace=T(Q1))
    rep = xc.check(repo, _case(repo))
    assert rep.findings == []


def test_gather_malformed_trace_is_an_error_view(repo):
    d = _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    (d / "trace.xtr").write_text("garbage\n")
    v = xc.gather(repo, TID)["ms1"][("rtl", "iverilog")]
    assert v.status == "error" and "trace.xtr" in v.result["reason"] and v.trace is None


def test_gather_result_not_matching_its_path_is_an_error_view(repo):
    d = _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    data = json.loads((d / "result.json").read_text())
    (d / "result.json").write_text(json.dumps({**data, "model_source": "other"}))
    v = xc.gather(repo, TID)["ms1"][("rtl", "iverilog")]
    assert v.status == "error" and "not its path" in v.result["reason"]


def test_gather_schema_invalid_result_is_an_error_view_not_a_traceback(repo):
    """Review (a) #4: the one schema-validated reader; a configs entry that is not an
    object is an error view, as it is for ``xut status record``."""
    d = _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    data = json.loads((d / "result.json").read_text())
    (d / "result.json").write_text(json.dumps({**data, "configs": ["c"]}))
    v = xc.gather(repo, TID)["ms1"][("rtl", "iverilog")]
    assert v.status == "error" and "invalid result.json" in v.result["reason"]


def _case(root):
    from xut.testspec import discover

    return next(c for c in discover(root) if c.id == TID)


def test_matrix_shows_every_status_with_its_reason():
    vs = views(
        V("python", EXP(Q0)),
        V("iverilog", T(Q0), status="fail", reason="1 mismatch"),
        V("xsim", None, status="skip", reason="runner unavailable: no vivado"),
        V("verilator", None, status="not-run", reason="no result.json"),
    )
    m = xc.matrix(vs)
    assert "| flow | python | xsim | iverilog | verilator |" in m
    assert "| rtl | pass | skip | fail | not-run |" in m
    assert "- rtl/xsim: skip: runner unavailable: no vivado" in m
    assert "- rtl/iverilog: fail: 1 mismatch" in m
    assert "- rtl/verilator: not-run: no result.json" in m


def test_check_declared_runner_without_result_is_not_run(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    rep = xc.check(repo, _case(repo))
    v = rep.views["ms1"][("rtl", "xsim")]
    assert (v.status, v.trace) == ("not-run", None)
    assert rep.verdict == "agree" and rep.exit_code == 0


def test_check_error_result_is_an_issue_exit_2(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    _result(repo, "rtl", "xsim", "ms1", TID, status="error", reason="compile failed")
    rep = xc.check(repo, _case(repo))
    assert rep.issues == ["ms1 rtl/xsim: error: compile failed"]
    assert rep.verdict == "incomplete" and rep.exit_code == 2


def test_check_config_error_inside_a_pass_is_an_issue(repo):
    _test_yaml(repo)
    exp = EXP({"a/S1": {"Q": "0"}, "b/S1": {"Q": "1"}})
    _result(repo, "rtl", "python", "ms1", TID, trace=exp)
    cfgs = [{"cfg": "a", "status": "pass"}, {"cfg": "b", "status": "error", "reason": "timeout"}]
    _result(
        repo,
        "rtl",
        "iverilog",
        "ms1",
        TID,
        status="error",
        reason="b: timeout",
        trace=T({"a/S1": {"Q": "0"}}),
        configs=cfgs,
    )
    rep = xc.check(repo, _case(repo))
    assert rep.findings == []
    assert rep.issues == ["ms1 rtl/iverilog: cfg b: error: timeout"]


def test_check_unexplained_fail_is_an_issue(repo):
    """A fail that no disagreement explains (e.g. a UNISIM runtime Error line, S16)."""
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0), status="fail", reason="model error")
    rep = xc.check(repo, _case(repo))
    assert rep.findings == [] and rep.exit_code == 2
    assert rep.issues == ["ms1 rtl/iverilog: fail not explained by any disagreement: model error"]


def test_check_single_trace_is_not_agreement(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    rep = xc.check(repo, _case(repo))
    assert rep.verdict == "uncompared" and rep.exit_code == 0


def test_check_nothing_run(repo):
    _test_yaml(repo)
    rep = xc.check(repo, _case(repo))
    assert rep.verdict == "not-run" and rep.views == {}


def test_coverage_gap_for_output_the_golden_model_does_not_model(repo):
    """PR A gate nit: compare() ignores actual-only ports; crosscheck surfaces them."""
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    both = {lbl: {**p, "QB": "1"} for lbl, p in Q0.items()}
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(both))
    rep = xc.check(repo, _case(repo))
    assert rep.coverage_gaps == [
        "ms1 rtl: QB observed by iverilog in cfg c, not modelled by the golden model"
    ]
    assert rep.exit_code == 0


def test_check_expected_divergence_naming_a_missing_finding_is_an_issue(repo):
    _test_yaml(repo, [ED])
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0, "inferred:s"))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q1), status="fail", reason="m")
    rep = xc.check(repo, _case(repo))
    assert classes(rep.findings) == ["known-divergence"]
    assert rep.issues == [f"expected_divergence names {ED['finding']}, which does not exist"]


def test_check_unmatched_expected_divergence_is_noted(repo):
    _test_yaml(repo, [ED])
    (repo / "findings").mkdir()
    (repo / ED["finding"]).write_text("# x\n")
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    rep = xc.check(repo, _case(repo))
    assert rep.unmatched_expected == [ED["finding"]] and rep.exit_code == 0


# --- finding stubs ------------------------------------------------------------------------

F = Finding(
    "doc-gap",
    "7series.FDRE.L1.gsr_init",
    "rtl",
    "unisim-2025.2",
    ("iverilog", "verilator", "xsim"),
    ("init0/S3 Q[0]: expected 0, got 1 (inferred:why)",),
)


def test_write_finding_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(xc, "_head", lambda root: "abc1234")
    monkeypatch.setattr(xc, "_today", lambda: "2026-09-26")
    p = xc.write_finding(tmp_path, "FDRE", F)
    assert p == tmp_path / "findings/FDRE-doc-gap-L1-gsr_init.md"
    assert p.read_text() == (
        "# FDRE: doc-gap in 7series.FDRE.L1.gsr_init\n"
        "\n"
        "- Class: doc-gap\n"
        "- Test: 7series.FDRE.L1.gsr_init\n"
        "- Flow / model source: rtl / unisim-2025.2\n"
        "- Runners: iverilog, verilator, xsim\n"
        "- First seen: 2026-09-26 at abc1234\n"
        "- Status: open\n"
        "\n"
        "## Evidence\n"
        "\n"
        "- init0/S3 Q[0]: expected 0, got 1 (inferred:why)\n"
        "\n"
        "## Analysis\n"
        "\n"
        "Not yet analysed. Explain the divergence against the cited UG953 page, then either\n"
        "correct the golden model (with its provenance) or add an `expected_divergence`\n"
        "entry to test.yaml pointing here. Never weaken the test (spec §8).\n"
    )


def test_write_finding_never_overwrites(tmp_path):
    p = xc.write_finding(tmp_path, "FDRE", F)
    p.write_text(p.read_text() + "analysed\n")
    before = p.read_text()
    assert xc.write_finding(tmp_path, "FDRE", F) is None
    assert p.read_text() == before


def test_write_finding_known_divergence_writes_nothing(tmp_path):
    k = Finding(
        "known-divergence", F.test_id, "rtl", "m", F.runners, F.points, True, "doc-gap", "X"
    )
    assert xc.write_finding(tmp_path, "FDRE", k) is None
    assert not (tmp_path / "findings").exists()


# --- the CLI --------------------------------------------------------------------------------


def _diverging(repo, expected_divergence=()):
    _test_yaml(repo, expected_divergence)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0, "inferred:silent"))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q1), status="fail", reason="1 mismatch")
    _result(repo, "rtl", "xsim", "ms1", TID, trace=T(Q1), status="fail", reason="1 mismatch")


def test_cli_unlisted_finding_exits_1_and_writes_json(repo):
    _diverging(repo)
    r = _xc("TOYFF")
    assert r.exit_code == 1, r.output
    assert "doc-gap" in r.output and "| rtl | pass | fail | fail |" in r.output
    data = json.loads((repo / f"build/crosscheck/{TID}.json").read_text())
    assert data["format"] == "xut-crosscheck 1" and data["verdict"] == "divergence"
    (f,) = data["findings"]
    assert (f["cls"], f["expected"], f["slug"]) == ("doc-gap", False, "doc-gap-L1-capture")
    assert data["model_sources"]["ms1"]["rtl/iverilog"]["status"] == "fail"


def test_cli_known_divergence_exits_0_still_reported(repo):
    _diverging(repo, [ED])
    (repo / "findings").mkdir()
    (repo / ED["finding"]).write_text("# TOYFF\n- Status: open\n")
    r = _xc(TID, "--write-findings")
    assert r.exit_code == 0, r.output
    assert "known-divergence" in r.output and "TOYFF-doc-gap-L1-capture" in r.output
    assert "of doc-gap" in r.output
    data = json.loads((repo / f"build/crosscheck/{TID}.json").read_text())
    (f,) = data["findings"]
    assert (f["cls"], f["of"], f["finding"]) == (
        "known-divergence",
        "doc-gap",
        "TOYFF-doc-gap-L1-capture",
    )
    assert data["verdict"] == "known-divergence"
    # no duplicate stub was created for the known divergence
    assert sorted(p.name for p in (repo / "findings").iterdir()) == ["TOYFF-doc-gap-L1-capture.md"]


def test_cli_write_findings_writes_a_stub_once(repo):
    _diverging(repo)
    r = _xc("TOYFF", "--write-findings")
    assert r.exit_code == 1
    p = repo / "findings/TOYFF-doc-gap-L1-capture.md"
    assert p.is_file() and f"wrote {p.relative_to(repo)}" in r.output
    r = _xc("TOYFF", "--write-findings")
    assert f"exists: {p.relative_to(repo)}" in r.output


def test_cli_clean_exit_0(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    r = _xc("TOYFF")
    assert r.exit_code == 0, r.output
    assert "agree" in r.output


def test_cli_nothing_run_exits_2(repo):
    _test_yaml(repo)
    r = _xc("TOYFF")
    assert r.exit_code == 2, r.output
    assert "not-run" in r.output


def test_cli_unmatched_selector_is_clean_error(repo):
    _test_yaml(repo)
    r = _xc("NOSUCH")
    assert r.exit_code == 1 and "NOSUCH" in r.output and "Traceback" not in r.output


# --- end to end: xut run, then xut crosscheck, on the TOYFF fixture ------------------------


def _demo(capsys, title: str, output: str) -> None:
    with capsys.disabled():
        print(f"\n[T17 demo: {title}]\n{output}")


@pytest.mark.container
def test_cli_run_then_crosscheck_on_the_toyff_fixture(work, toy, monkeypatch, capsys):
    """`xut run --runner python --runner iverilog` then `xut crosscheck TOYFF`, against
    two toy model sources: `toyff-good` (a correct TOYFF.v) and `toyff-bad` (Q
    inverted). The good source agrees with the golden model; the bad one is a
    doc-vs-model finding (ToyDff's provenance is doc:1), until an expected_divergence
    lists it, when it is still reported, as known-divergence, and the exit is 0. The
    two sources, which disagree with each other everywhere, are never cross-compared."""
    import dataclasses

    from test_runner_iverilog import _copy_toy, make_model_source

    d = _copy_toy(work)
    good = make_model_source(work / "good")
    bad = make_model_source(work / "bad")
    v = bad.unisims / "TOYFF.v"
    v.write_text(v.read_text().replace("assign Q = q;", "assign Q = ~q;"))
    good = dataclasses.replace(good, name="toyff-good")
    bad = dataclasses.replace(bad, name="toyff-bad")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    run = ["run", "--runner", "python", "--runner", "iverilog", "--style", "vector"]
    run += ["--style", "sv", "TOYFF"]

    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": good)
    r = CliRunner().invoke(main, run)
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(main, ["crosscheck", "TOYFF"])
    _demo(capsys, "crosscheck after `xut run` on toyff-good", r.output)
    cap = json.loads((work / f"build/crosscheck/{TID}.json").read_text())
    assert cap["verdict"] == "agree" and cap["findings"] == []
    assert cap["model_sources"]["toyff-good"]["rtl/xsim"]["status"] == "not-run"
    assert r.exit_code == 0, r.output  # the cocotb test is not-run; others agree/uncompared

    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": bad)
    r = CliRunner().invoke(main, run)
    assert r.exit_code == 1, r.output  # iverilog fails against the golden model
    r = CliRunner().invoke(main, ["crosscheck", TID, "--write-findings"])
    _demo(capsys, "crosscheck with toyff-bad also run", r.output)
    assert r.exit_code == 1, r.output
    cap = json.loads((work / f"build/crosscheck/{TID}.json").read_text())
    assert set(cap["model_sources"]) == {"toyff-good", "toyff-bad"}
    (f,) = cap["findings"]  # none from comparing good with bad
    assert (f["cls"], f["model_source"], f["runners"]) == (
        "doc-vs-model",
        "toyff-bad",
        ["iverilog"],
    )
    stub = work / "findings/TOYFF-doc-vs-model-L1-capture.md"
    assert stub.is_file() and "- Status: open" in stub.read_text()

    doc = yaml.safe_load((d / "test.yaml").read_text())
    doc["tests"][0]["expected_divergence"] = [
        {
            "finding": "findings/TOYFF-doc-vs-model-L1-capture.md",
            "cls": "doc-vs-model",
            "runners": ["iverilog"],
        }
    ]
    (d / "test.yaml").write_text(yaml.safe_dump(doc))
    before = stub.read_text()
    r = CliRunner().invoke(main, ["crosscheck", TID, "--write-findings"])
    _demo(capsys, "crosscheck after listing the expected divergence", r.output)
    assert r.exit_code == 0, r.output
    cap = json.loads((work / f"build/crosscheck/{TID}.json").read_text())
    (f,) = cap["findings"]
    assert (f["cls"], f["of"], f["finding"]) == (
        "known-divergence",
        "doc-vs-model",
        "TOYFF-doc-vs-model-L1-capture",
    )
    assert f["points"] and cap["verdict"] == "known-divergence"
    assert stub.read_text() == before and len(list((work / "findings").iterdir())) == 1


@pytest.mark.vivado
@pytest.mark.container
def test_cli_run_python_iverilog_xsim_then_crosscheck(work, toy, monkeypatch, capsys):
    """The same with xsim too (the toy source is named unisim-2025.2 so xsim runs; test
    label only, it holds just TOYFF.v): python, iverilog and xsim all agree."""
    import dataclasses

    from test_runner_iverilog import _copy_toy, make_model_source

    from xut.runners import RUNNERS
    from xut.runners.xsim import MODEL_SOURCE, XsimRunner

    _copy_toy(work)
    ms = dataclasses.replace(make_model_source(work / "ms"), name=MODEL_SOURCE)
    toyff = ms.unisims / "TOYFF.v"

    class ToyXsim(XsimRunner):
        def __init__(self) -> None:
            super().__init__(extra_files=[toyff])

    monkeypatch.setitem(RUNNERS, "xsim", ToyXsim)
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: work)
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    args = ["run", "--runner", "python", "--runner", "iverilog", "--runner", "xsim"]
    r = CliRunner().invoke(main, [*args, "--style", "vector", "--style", "sv", "TOYFF"])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(main, ["crosscheck", "TOYFF"])
    _demo(capsys, "crosscheck after python + iverilog + xsim", r.output)
    assert r.exit_code == 0, r.output
    for tid in (TID, "7series.TOYFF.L1.sv_basic"):
        cap = json.loads((work / f"build/crosscheck/{tid}.json").read_text())
        assert cap["verdict"] == "agree" and cap["findings"] == [], cap


# --- fix round 1 --------------------------------------------------------------------------


def _probe_c_d_views():
    return views(V("python", EXP(Q0, "inferred:s")), V("iverilog", T(Q1)), V("xsim", T(Q1)))


def test_s17_entry_with_another_finding_id_is_an_issue_not_a_match():
    """Probe C: class and runners match, but the entry names another test's finding."""
    other = {**ED, "finding": "findings/TOYFF-doc-gap-L1-other_test.md"}
    issues: list[str] = []
    (f,) = classify(TID, _probe_c_d_views(), (other,), issues)
    assert f.cls == "doc-gap" and not f.expected
    assert len(issues) == 1 and "TOYFF-doc-gap-L1-other_test" in issues[0]
    assert "TOYFF-doc-gap-L1-capture" in issues[0] and "not matched" in issues[0]


def test_s17_model_source_and_flow_scope():
    """Probe D: an entry scoped to another model source (or flow) does not match."""
    for scope in ({"model_sources": ["ms2"]}, {"flows": ["vivado"]}):
        (f,) = classify(TID, _probe_c_d_views(), ({**ED, **scope},))
        assert f.cls == "doc-gap", scope
    for scope in ({"model_sources": ["ms1", "ms2"]}, {"flows": ["rtl"]}):
        (f,) = classify(TID, _probe_c_d_views(), ({**ED, **scope},))
        assert f.cls == "known-divergence", scope


def test_s17_runners_are_required_no_wildcard():
    e = {k: v for k, v in ED.items() if k != "runners"}
    (f,) = classify(TID, _probe_c_d_views(), (e,))
    assert f.cls == "doc-gap"


def test_doc_finding_lists_only_observing_runners():
    """Expected x: the 2-state verilator cannot observe it; only iverilog disagrees."""
    exp = EXP({"c/S1": {"Q": "x"}})
    vs = views(
        V("python", exp),
        V("iverilog", T({"c/S1": {"Q": "1"}})),
        V("verilator", T({"c/S1": {"Q": "1"}})),
    )
    (f,) = classify(TID, vs)
    assert (f.cls, f.runners) == ("doc-vs-model", ("iverilog",))


def test_pass_without_trace_is_an_error_view(repo):
    for style in ("vector", "sv"):
        tid = f"{TID}_{style}"
        d = _result(
            repo,
            "rtl",
            "iverilog",
            "ms1",
            tid,
            style=style,
            configs=[{"cfg": "c", "status": "pass", "reason": None}],
        )
        assert not (d / "trace.xtr").exists()
        v = xc.gather(repo, tid)["ms1"][("rtl", "iverilog")]
        assert v.status == "error" and "wrote no trace.xtr" in v.result["reason"], style


def test_check_pass_without_trace_is_an_issue(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms1", TID, configs=[{"cfg": "c", "status": "pass"}])
    rep = xc.check(repo, _case(repo))
    assert rep.exit_code == 2 and rep.verdict == "incomplete"
    assert "wrote no trace.xtr" in rep.issues[0]


def test_gather_trace_without_result_is_an_error_view(repo):
    d = repo / "build/rtl/iverilog/ms1" / TID
    d.mkdir(parents=True)
    xtr.dump(T(Q0), d / "trace.xtr")
    v = xc.gather(repo, TID)["ms1"][("rtl", "iverilog")]
    assert v.status == "error" and "without result.json" in v.result["reason"]


def test_probe_b_golden_config_absent_or_skipped_is_visible(repo):
    """The golden model ran a and b. iverilog's result omits b entirely (an issue);
    xsim skipped b by config_exclusions (a coverage note). Never agreement."""
    _test_yaml(repo)
    both = {"a/S1": {"Q": "0"}, "b/S1": {"Q": "1"}}
    only_a = {"a/S1": {"Q": "0"}}
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(both))
    _result(
        repo,
        "rtl",
        "iverilog",
        "ms1",
        TID,
        trace=T(only_a),
        configs=[{"cfg": "a", "status": "pass"}],
    )
    _result(
        repo,
        "rtl",
        "xsim",
        "ms1",
        TID,
        trace=T(only_a),
        configs=[
            {"cfg": "a", "status": "pass"},
            {"cfg": "b", "status": "skip", "reason": "excluded: hw only"},
        ],
    )
    rep = xc.check(repo, _case(repo))
    assert rep.findings == []
    assert rep.issues == [
        "ms1 rtl/iverilog: cfg b, run by the golden model, is absent from its result"
    ]
    assert rep.coverage_gaps == ["ms1 rtl/xsim: cfg b skipped: excluded: hw only"]
    assert rep.exit_code == 2
    data = rep.to_dict()
    assert data["coverage_gaps"] == rep.coverage_gaps and data["issues"] == rep.issues


def test_x_dependence_does_not_explain_a_fail(repo):
    _test_yaml(repo, runners={"python": "yes", "verilator": "yes"})
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    _result(
        repo,
        "rtl",
        "verilator",
        "ms1",
        TID,
        trace=T(Q0),
        status="fail",
        reason="r",
        x_dependence=True,
        seeds={"stimulus": 1, "x": [1, 2]},
    )
    rep = xc.check(repo, _case(repo))
    assert classes(rep.findings) == ["x-dependence"]
    assert "fail not explained" in " ".join(rep.issues)


def test_not_run_placeholders_for_every_declared_flow(repo):
    _test_yaml(repo, runners={"python": "yes", "iverilog": "yes", "hw": "yes"})
    doc_p = repo / "tests/7series/register/TOYFF/test.yaml"
    doc = yaml.safe_load(doc_p.read_text())
    doc["tests"][0]["flows"] = ["rtl", "vivado"]
    doc_p.write_text(yaml.safe_dump(doc))
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    rep = xc.check(repo, _case(repo))
    got = {k: v.status for k, v in rep.views["ms1"].items()}
    assert got == {
        ("rtl", "python"): "pass",
        ("rtl", "iverilog"): "not-run",
        ("vivado", "iverilog"): "not-run",
        ("vivado", "hw"): "not-run",
    }


def test_coverage_gap_per_flow_and_config(repo):
    _test_yaml(repo)
    exp = EXP({"a/S1": {"Q": "0"}, "b/S1": {"Q": "0"}})
    _result(repo, "rtl", "python", "ms1", TID, trace=exp)
    _result(
        repo,
        "rtl",
        "iverilog",
        "ms1",
        TID,
        trace=T({"a/S1": {"Q": "0"}, "b/S1": {"Q": "0", "QB": "1"}}),
    )
    _result(
        repo,
        "vivado",
        "iverilog",
        "ms1",
        TID,
        trace=T({"a/S1": {"Q": "0", "QB": "1"}, "b/S1": {"Q": "0"}}),
    )
    rep = xc.check(repo, _case(repo))
    assert rep.coverage_gaps == [
        "ms1 rtl: QB observed by iverilog in cfg b, not modelled by the golden model",
        "ms1 vivado: QB observed by iverilog in cfg a, not modelled by the golden model",
    ]


def test_record_finding_on_a_second_model_source_appends_once(tmp_path, monkeypatch):
    monkeypatch.setattr(xc, "_head", lambda root: "abc1234")
    monkeypatch.setattr(xc, "_today", lambda: "2026-09-26")
    gh = Finding(F.cls, F.test_id, "rtl", "unisim-gh-2020.1", F.runners, F.points)
    assert gh.slug == F.slug
    assert xc.record_finding(tmp_path, "FDRE", F)[0] == "wrote"
    p = xc.finding_path(tmp_path, "FDRE", F)
    first = p.read_text()
    assert xc.record_finding(tmp_path, "FDRE", gh) == ("recorded", p)
    assert p.read_text() == first + "- Also seen: rtl / unisim-gh-2020.1 (2026-09-26 at abc1234)\n"
    after = p.read_text()
    assert xc.record_finding(tmp_path, "FDRE", gh) == ("exists", p)
    assert xc.record_finding(tmp_path, "FDRE", F) == ("exists", p)
    assert xc.write_finding(tmp_path, "FDRE", gh) is None and p.read_text() == after


def test_cli_write_findings_recorded_for_a_second_model_source(repo):
    _diverging(repo)
    _result(repo, "rtl", "python", "ms2", TID, trace=EXP(Q0, "inferred:silent"))
    _result(repo, "rtl", "iverilog", "ms2", TID, trace=T(Q1), status="fail", reason="m")
    _result(repo, "rtl", "xsim", "ms2", TID, trace=T(Q1), status="fail", reason="m")
    r = _xc("TOYFF", "--write-findings")
    rel = "findings/TOYFF-doc-gap-L1-capture.md"
    assert f"wrote {rel}" in r.output and f"recorded: {rel}" in r.output
    r = _xc("TOYFF", "--write-findings")
    assert r.output.count(f"exists: {rel}") == 2


def test_cli_all_uncompared_exits_2(repo):
    _test_yaml(repo)
    _result(repo, "rtl", "iverilog", "ms1", TID, trace=T(Q0))
    r = _xc("TOYFF")
    assert r.exit_code == 2, r.output
    assert "uncompared" in r.output


def test_cli_unit_without_tests_is_exit_0(repo):
    _test_yaml(repo)
    (repo / "docs").mkdir()
    (repo / "docs/work-units.yaml").write_text(
        "family: 7series\nunits:\n  flops: {group: register, primitives: [FDRE]}\n"
    )
    r = _xc("unit:flops", "--model-source", "unisim-gh-2020.1")
    assert r.exit_code == 0, r.output
    assert "no tests selected (unit:flops)" in r.output
    r = _xc("unit:nosuch")
    assert r.exit_code == 1 and "unit:nosuch" in r.output


def test_cli_model_source_restricts_the_report(repo):
    _diverging(repo)  # ms1: a doc-gap finding
    _result(repo, "rtl", "python", "ms2", TID, trace=EXP(Q0))
    _result(repo, "rtl", "iverilog", "ms2", TID, trace=T(Q0))
    r = _xc("TOYFF", "--model-source", "ms2")
    assert r.exit_code == 0, r.output
    data = json.loads((repo / f"build/crosscheck/{TID}.json").read_text())
    assert list(data["model_sources"]) == ["ms2"] and data["findings"] == []
    assert _xc("TOYFF").exit_code == 1  # both sources: ms1's finding is back


def test_cli_model_source_must_be_known(repo):
    _test_yaml(repo)
    r = _xc("TOYFF", "--model-source", "unisim-typo")
    assert r.exit_code == 1 and "unknown model source 'unisim-typo'" in r.output
    assert "unisim-gh-2020.1" in r.output  # the known ones are listed
    _result(repo, "rtl", "python", "ms1", TID, trace=EXP(Q0))
    assert "unknown model source" not in _xc("TOYFF", "--model-source", "ms1").output
