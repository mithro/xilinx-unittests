# SPDX-License-Identifier: Apache-2.0
"""Runner template (result.json on every exit path), the python golden runner, run_tests."""

import dataclasses
import hashlib
import json
import os
import shutil
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_golden import ToyDff

from xut import schemas
from xut.catalog.model import CatalogEntry
from xut.formats import xtr, xvec
from xut.modelsrc import ModelSource
from xut.run import run_tests
from xut.runners import RUNNERS
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    expected_trace,
    load_generated,
    timeout_for,
    workdir,
    worst,
)
from xut.runners.python import PythonRunner
from xut.testspec import TestCase, discover
from xut_models.base import ModelUnsupported

FIX = Path(__file__).parent / "fixtures"
TOY_DIR = FIX / "tests/7series/register/TOYFF"

TOY_ENTRY = CatalogEntry(
    name="TOYFF",
    family="7series",
    group="REGISTER",
    subgroup="SDR",
    description="toy D flip-flop",
    doc={"guide": "UG953", "edition": "2026.1", "page": 1},
    model={"library": "unisims", "file": "TOYFF.v"},
    ports=[
        {"name": "Q", "direction": "output", "width": 1, "cls": "data", "doc_function": "Q"},
        {"name": "C", "direction": "input", "width": 1, "cls": "clock", "doc_function": "C"},
        {"name": "D", "direction": "input", "width": 1, "cls": "data", "doc_function": "D"},
    ],
    attributes=[
        {
            "name": "INIT",
            "kind": "bits",
            "width": 1,
            "default": "1'b0",
            "allowed": ["1'b0", "1'b1"],
        },
    ],
)


@pytest.fixture
def toy(monkeypatch):
    """TOYFF without a catalog file or a xut_models module: ToyDff is its golden model."""
    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: TOY_ENTRY)
    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: ToyDff)


@pytest.fixture
def ctx(tmp_path):
    return RunContext(tmp_path, "rtl", ModelSource("unisim-test", tmp_path / "ms"))


def _case() -> TestCase:
    return discover(FIX)[0]


def _result(d: Path) -> dict:
    data = json.loads((d / "result.json").read_text())
    schemas.validate(data, "result")
    return data


def _sv_case(**kw) -> TestCase:
    """The TOYFF case as an sv test with the given configs (no python run needed)."""
    cfgs = kw.pop("cfgs", ["default"])
    return dataclasses.replace(
        _case(),
        style="sv",
        source="sv/tb.sv",
        configs=[{"cfg": c, "attrs": {}} for c in cfgs],
        runners={**_case().runners, "fake": "yes"},
        **kw,
    )


def _toy_trace(label: str = "S0") -> xtr.Trace:
    t = xtr.Trace({"runner": "fake", "flow": "rtl", "model": "m", "seed": "0"})
    t.add(label, {"Q": "1"})
    return t


class Fake(Runner):
    name = "fake"
    calls: list[str] = []

    def run_config(self, case, cfg, cfgdir, ctx):
        type(self).calls.append(cfg)
        xtr.dump(_toy_trace(), cfgdir / "trace.xtr")
        (cfgdir / "run.log").write_text(f"ran {cfg}\n")
        return ConfigResult(cfg, "pass")


# --- worst / workdir / timeouts ---------------------------------------------------


def test_worst():
    assert worst(["pass", "fail", "error"]) == "fail"
    assert worst(["pass", "error"]) == "error"
    assert worst(["skip", "pass"]) == "pass"
    assert worst([]) == "skip"


def test_workdir_includes_model_source(ctx):
    assert workdir(ctx, "iverilog", "t.id") == ctx.root / "build/rtl/iverilog/unisim-test/t.id"


def test_timeout_precedence(ctx):
    c = _case()
    assert timeout_for(c, ctx) == 600
    assert timeout_for(c, dataclasses.replace(ctx, timeout_s=30)) == 30
    assert (
        timeout_for(dataclasses.replace(c, timeout_s=7), dataclasses.replace(ctx, timeout_s=30))
        == 7
    )


# --- the template: every exit path writes result.json -----------------------------


def test_declared_unsupported_is_skip_with_reason(ctx):
    class Hw(Fake):
        name = "hw"

    res = Hw().run(_case(), ctx)
    d = workdir(ctx, "hw", _case().id)
    data = _result(d)
    assert res.status == data["status"] == "skip"
    assert "toy" in data["reason"] and data["reason"].startswith("declared unsupported")
    assert (d / "run.log").is_file()


def test_undeclared_runner_is_skip(ctx):
    res = Fake().run(_case(), ctx)  # "fake" is not in the fixture's runners
    assert (res.status, res.reason) == ("skip", "declared unsupported: not declared")


def test_style_not_run_is_skip(ctx):
    class VecOnly(Fake):
        styles = frozenset({"vector"})

    res = VecOnly().run(_sv_case(), ctx)
    assert res.status == "skip" and "does not run sv tests" in res.reason
    _result(workdir(ctx, "fake", _case().id))


def test_unavailable_is_skip(ctx):
    class Gone(Fake):
        def available(self, ctx):
            return False, "no simulator here"

    res = Gone().run(_sv_case(), ctx)
    assert (res.status, res.reason) == ("skip", "runner unavailable: no simulator here")


def test_run_config_exception_is_error_with_text(ctx):
    class Boom(Fake):
        def run_config(self, case, cfg, cfgdir, ctx):
            raise RuntimeError("simulator exploded")

    res = Boom().run(_sv_case(), ctx)
    d = workdir(ctx, "fake", _case().id)
    data = _result(d)
    assert data["status"] == "error" and "simulator exploded" in data["reason"]
    assert data["configs"][0]["status"] == "error"
    assert "simulator exploded" in (d / "run.log").read_text()
    assert res.status == "error"


@pytest.mark.parametrize("where", ["tools", "finish", "configs"])
def test_failure_outside_run_config_still_writes_error_result(ctx, where):
    def boom(*a, **k):
        raise RuntimeError(f"{where} broke")

    Broken = type("Broken", (Fake,), {where: boom})
    res = Broken().run(_sv_case(), ctx)
    d = workdir(ctx, "fake", _case().id)
    data = _result(d)
    assert res.status == data["status"] == "error"
    assert f"{where} broke" in data["reason"]
    assert f"{where} broke" in (d / "run.log").read_text()


def test_malformed_trace_is_config_error(ctx):
    class Garbage(Fake):
        def run_config(self, case, cfg, cfgdir, ctx):
            (cfgdir / "trace.xtr").write_text("not a trace\n")
            return ConfigResult(cfg, "pass")

    res = Garbage().run(_sv_case(), ctx)
    data = _result(workdir(ctx, "fake", _case().id))
    assert res.status == data["status"] == "error"
    assert "malformed trace.xtr" in data["configs"][0]["reason"]


def test_traces_and_logs_are_concatenated(ctx):
    res = Fake().run(_sv_case(cfgs=["a", "b"]), ctx)
    d = workdir(ctx, "fake", _case().id)
    t = xtr.load(d / "trace.xtr")
    assert list(t.samples) == ["a/S0", "b/S0"]
    assert t.header["model"] == "unisim-test" and t.header["runner"] == "fake"
    log = (d / "run.log").read_text()
    assert "ran a" in log and "ran b" in log
    assert res.status == "pass" and res.reason is None
    data = _result(d)
    assert data["model_source"] == "unisim-test"
    assert data["seeds"]["stimulus"] is not None and data["started"]


def test_config_exclusions_skip_with_reason(ctx):
    Fake.calls = []
    case = _sv_case(cfgs=["i0_d0_r0", "i0_d1_r0"], config_exclusions={"fake": {"*_d1_*": "reason"}})
    res = Fake().run(case, ctx)
    assert Fake.calls == ["i0_d0_r0"]
    data = _result(workdir(ctx, "fake", case.id))
    by = {c["cfg"]: c for c in data["configs"]}
    assert (by["i0_d1_r0"]["status"], by["i0_d1_r0"]["reason"]) == ("skip", "excluded: reason")
    assert by["i0_d0_r0"]["status"] == "pass"
    assert res.status == data["status"] == "pass"


def test_all_configs_excluded_is_skip_with_reason(ctx):
    case = _sv_case(cfgs=["a"], config_exclusions={"fake": {"*": "never on fake"}})
    res = Fake().run(case, ctx)
    assert (res.status, res.reason) == ("skip", "a: excluded: never on fake")
    _result(workdir(ctx, "fake", case.id))


def test_rerun_starts_from_a_fresh_directory(ctx):
    d = workdir(ctx, "fake", _case().id)
    d.mkdir(parents=True)
    (d / "stale.txt").write_text("old")
    Fake().run(_sv_case(), ctx)
    assert not (d / "stale.txt").exists()


def test_vector_runner_without_python_run_is_error(ctx):
    case = dataclasses.replace(_case(), runners={**_case().runners, "fake": "yes"})
    res = Fake().run(case, ctx)
    assert res.status == "error" and "configs.json missing" in res.reason


# --- the python runner ------------------------------------------------------------


def test_python_runner_on_toyff(ctx, toy):
    res = PythonRunner().run(_case(), ctx)
    d = workdir(ctx, "python", _case().id)
    assert res.status == "pass", res.reason
    for cfg in ("init0", "init1"):
        assert (d / f"cfg-{cfg}/expected.xtr").is_file()
        assert (d / f"cfg-{cfg}/stim.xvec").is_file()
    assert (d / "cfg-init0/dut/xut_dut.map.json").is_file()
    assert json.loads((d / "configs.json").read_text()) == ["init0", "init1"]
    data = _result(d)
    assert "claim:TOYFF.C1" in data["bins_reached"]
    assert data["tools"]["python"]
    c0 = data["configs"][0]
    stim = (d / "cfg-init0/stim.xvec").read_bytes()
    assert c0["stimulus_sha256"] == hashlib.sha256(stim).hexdigest()
    exp = (d / "cfg-init0/expected.xtr").read_bytes()
    assert c0["trace_sha256"] == hashlib.sha256(exp).hexdigest()
    t = xtr.load(d / "trace.xtr")
    assert t.header["kind"] == "expected" and t.header["model"] == "golden"
    assert "init0/S0" in t.samples and "init1/S0" in t.samples
    # the stimulus carries its hw renderability
    assert xvec.load(d / "cfg-init0/stim.xvec").hw_renderable is not None


def _tmp_toy(tmp_path: Path, gen_body: str, source: str = "vectors/gen.py:gen") -> TestCase:
    """A copy of the TOYFF test whose generator is ``gen_body``."""
    d = tmp_path / "tests/7series/register/TOYFF"
    shutil.copytree(TOY_DIR, d)
    (d / "vectors/gen.py").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n" + textwrap.dedent(gen_body)
    )
    return dataclasses.replace(discover(tmp_path)[0], source=source)


def test_python_reject_config_writes_header_only_expected(ctx, toy, tmp_path):
    case = _tmp_toy(
        tmp_path,
        """
        def gen(ctx):
            b = ctx.dut("rej", expect="reject", INIT=1)
            b.cycle("C")
            yield b.build()
        """,
    )
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason
    t = xtr.load(workdir(ctx, "python", case.id) / "cfg-rej/expected.xtr")
    assert t.samples == {} and t.header["expect"] == "reject" and t.header["kind"] == "expected"


def test_python_invalid_stimulus_is_error(ctx, toy, tmp_path):
    case = _tmp_toy(
        tmp_path,
        """
        from xut.formats.xvec import Event

        def gen(ctx):
            b = ctx.dut("bad", INIT=0)
            b.set(D=1)
            b.cycle("C")
            v = b.build()
            i, e = next((i, e) for i, e in enumerate(v.events) if e.op == "set" and e.t > 0)
            v.events.insert(i + 1, Event(e.t, "sample", "BAD"))
            yield v
        """,
    )
    res = PythonRunner().run(case, ctx)
    assert res.status == "error" and "stimulus violates class rules" in res.reason
    assert json.loads((workdir(ctx, "python", case.id) / "configs.json").read_text()) == ["bad"]


def test_python_model_unsupported_is_skip_with_reason(ctx, toy, monkeypatch):
    class NoX(ToyDff):
        def power_on(self):
            raise ModelUnsupported("GTS is not modelled")

    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: NoX)
    res = PythonRunner().run(_case(), ctx)
    assert res.status == "skip" and "GTS is not modelled" in res.reason
    _result(workdir(ctx, "python", _case().id))


def test_python_no_model_is_skip_with_reason(ctx, toy, monkeypatch):
    def none(family, prim):
        raise LookupError(f"no golden model for {family}/{prim}")

    monkeypatch.setattr("xut_models.registry.get", none)
    res = PythonRunner().run(_case(), ctx)
    assert res.status == "skip" and "no golden model for 7series/TOYFF" in res.reason
    # the stimulus is still written: only the expectation is missing
    assert (workdir(ctx, "python", _case().id) / "cfg-init0/stim.xvec").is_file()


def test_python_generator_crash_is_error(ctx, toy, tmp_path):
    case = _tmp_toy(tmp_path, "def gen(ctx):\n    raise ValueError('generator bug')\n")
    res = PythonRunner().run(case, ctx)
    assert res.status == "error" and "generator bug" in res.reason


def test_python_frozen_xvec_source(ctx, toy, tmp_path):
    PythonRunner().run(_case(), ctx)
    stim = workdir(ctx, "python", _case().id) / "cfg-init1/stim.xvec"
    case = _tmp_toy(tmp_path, "", source="vectors/frozen.xvec")
    shutil.copy(stim, case.test_dir / "vectors/frozen.xvec")
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason
    assert [c.cfg for c in res.configs] == ["init1"]


def test_python_skips_non_vector_tests(ctx):
    res = PythonRunner().run(dataclasses.replace(_sv_case(), runners={"python": "yes"}), ctx)
    assert res.status == "skip" and "does not run sv tests" in res.reason


# --- other runners read the python run --------------------------------------------


class FakeIverilog(Runner):
    name = "iverilog"

    def run_config(self, case, cfg, cfgdir, ctx):
        exp = expected_trace(ctx, case, cfg)
        shutil.copy(exp, cfgdir / "trace.xtr")
        return ConfigResult(cfg, "pass")


def test_python_error_config_is_error_not_dropped(ctx, toy, monkeypatch):
    class HalfBroken(ToyDff):
        def power_on(self):
            if self.attrs.get("INIT") == "1'b1":
                raise RuntimeError("model bug")
            super().power_on()

    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: HalfBroken)
    py = PythonRunner().run(_case(), ctx)
    assert py.status == "error"
    gen = load_generated(ctx, _case())
    assert [g[0] for g in gen] == ["init0", "init1"]
    assert gen[0][2].is_file() and not gen[1][2].exists()
    res = FakeIverilog().run(_case(), ctx)
    by = {c.cfg: c for c in res.configs}
    assert set(by) == {"init0", "init1"}
    assert by["init0"].status == "pass"
    assert by["init1"].status == "error"
    assert by["init1"].reason.startswith("no expected trace (python: error: ")
    assert "model bug" in by["init1"].reason
    assert res.status == "error"


# --- run_tests ----------------------------------------------------------------------


def test_run_tests_schedules_python_first(ctx, toy, monkeypatch, capsys):
    order: list[str] = []

    class RecPython(PythonRunner):
        def run(self, case, ctx):
            order.append("python")
            return super().run(case, ctx)

    class RecIverilog(FakeIverilog):
        def run(self, case, ctx):
            order.append("iverilog")
            return super().run(case, ctx)

    monkeypatch.setitem(RUNNERS, "python", RecPython)
    monkeypatch.setitem(RUNNERS, "iverilog", RecIverilog)
    results = run_tests([_case()], ["iverilog"], ctx)
    assert order == ["python", "iverilog"]
    assert [(r.runner, r.status) for r in results] == [("python", "pass"), ("iverilog", "pass")]
    out = capsys.readouterr().out
    assert "progress: done=1 total=2" in out and "progress: done=2 total=2" in out
    summary = json.loads((ctx.root / "build/rtl/summary.json").read_text())
    assert [(r["runner"], r["status"]) for r in summary["results"]] == [
        ("python", "pass"),
        ("iverilog", "pass"),
    ]


def test_run_tests_runner_that_cannot_start_still_writes_result(ctx, monkeypatch):
    class Unbuildable(Fake):
        def __init__(self):
            raise RuntimeError("cannot construct")

    monkeypatch.setitem(RUNNERS, "fake", Unbuildable)
    [res] = run_tests([_sv_case()], ["fake"], ctx)
    assert res.status == "error" and "cannot construct" in res.reason
    _result(workdir(ctx, "fake", _case().id))


def test_run_tests_unknown_runner_is_error(ctx):
    from xut.errors import XutError

    with pytest.raises(XutError, match="nosuch"):
        run_tests([_case()], ["nosuch"], ctx)


# --- tool versions under threads ------------------------------------------------------


@pytest.mark.container
def test_sim_tool_versions_from_16_threads(monkeypatch, tmp_path):
    from xut import container

    monkeypatch.setattr(container, "_VERSIONS", {})
    ex = container.DockerExecutor(root=tmp_path)
    with ThreadPoolExecutor(16) as pool:
        got = list(pool.map(lambda _: container.sim_tool_versions(ex, tmp_path), range(16)))
    assert all(g == got[0] for g in got)
    assert set(got[0]) == {"iverilog", "verilator", "cocotb"}
    assert all(v and v != "unknown" for v in got[0].values())


def test_python_fixture_l0_reject_end_to_end(ctx, toy):
    """The fixture's l0_reject (INIT=1'bx, expect=reject; Ruling S12) through python:
    pass, with dut/, stim.xvec and a header-only expected.xtr for init_x."""
    case = dataclasses.replace(
        _case(), id="7series.TOYFF.L0.reject", level="L0", source="vectors/gen.py:l0_reject"
    )
    res = PythonRunner().run(case, ctx)
    assert res.status == "pass", res.reason
    d = workdir(ctx, "python", case.id)
    assert json.loads((d / "configs.json").read_text()) == ["init_x"]
    cd = d / "cfg-init_x"
    assert "INIT(1'bx)" in (cd / "dut/xut_dut.v").read_text().replace(" ", "")
    vec = xvec.load(cd / "stim.xvec")
    assert vec.expect == "reject" and vec.attrs["INIT"] == "1'bx"
    t = xtr.load(cd / "expected.xtr")
    assert t.samples == {} and t.header["expect"] == "reject"
    assert expected_trace(ctx, case, "init_x") == cd / "expected.xtr"
    assert res.bins_reached == []  # nothing replayed


# --- fix round 1 ----------------------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_undeletable_stale_dir_is_error_result_not_crash(ctx, monkeypatch):
    monkeypatch.setitem(RUNNERS, "fake", Fake)
    d = workdir(ctx, "fake", _case().id)
    locked = d / "locked"
    locked.mkdir(parents=True)
    (locked / "stale").write_text("old")
    locked.chmod(0o500)
    try:
        res = Fake().run(_sv_case(), ctx)
        assert res.status == "error" and "Permission" in res.reason
        assert _result(d)["status"] == "error"
        # and through run_tests: the invocation completes, with a summary
        [r] = run_tests([_sv_case()], ["fake"], ctx)
        assert r.status == "error"
        assert (ctx.root / "build/rtl/summary.json").is_file()
    finally:
        locked.chmod(0o700)


def test_run_tests_survives_a_run_that_raises(ctx, monkeypatch):
    class Raises(Fake):
        def run(self, case, ctx):
            raise RuntimeError("run() itself is broken")

    monkeypatch.setitem(RUNNERS, "fake", Raises)
    [res] = run_tests([_sv_case()], ["fake"], ctx)
    assert res.status == "error" and "run() itself is broken" in res.reason
    _result(workdir(ctx, "fake", _case().id))


def test_iverilog_vz_inherits_verilator_exclusions(ctx):
    class Vz(Fake):
        name = "iverilog-vz"

    Fake.calls = []
    case = _sv_case(cfgs=["a", "b"], config_exclusions={"verilator": {"b": "x inputs"}})
    case = dataclasses.replace(case, runners={**case.runners, "verilator": "yes"})
    res = Vz().run(case, ctx)
    assert Fake.calls == ["a"]
    assert [(c.cfg, c.status, c.reason) for c in res.configs][1] == (
        "b",
        "skip",
        "excluded: x inputs",
    )


def test_reason_lists_fail_and_error_configs(ctx):
    class Mixed(Fake):
        def run_config(self, case, cfg, cfgdir, ctx):
            xtr.dump(_toy_trace(), cfgdir / "trace.xtr")
            if cfg == "a":
                return ConfigResult(cfg, "fail", "Q mismatch", mismatches=1)
            raise RuntimeError("sim crashed")

    res = Mixed().run(_sv_case(cfgs=["a", "b"]), ctx)
    assert res.status == "fail"
    assert "a: Q mismatch" in res.reason and "b: RuntimeError: sim crashed" in res.reason


def test_pass_with_skipped_configs_says_so(ctx):
    case = _sv_case(cfgs=["a", "b"], config_exclusions={"fake": {"b": "hw only"}})
    res = Fake().run(case, ctx)
    assert res.status == "pass"
    assert res.reason == "1 config(s) skipped: b: excluded: hw only"
    _result(workdir(ctx, "fake", case.id))


def test_exclusion_glob_matching_nothing_is_logged(ctx):
    case = _sv_case(cfgs=["a"], config_exclusions={"fake": {"zz*": "never"}})
    Fake().run(case, ctx)
    log = (workdir(ctx, "fake", case.id) / "run.log").read_text()
    assert "glob 'zz*' matched no configuration" in log


def test_pass_without_trace_is_error(ctx):
    class NoTrace(Fake):
        def run_config(self, case, cfg, cfgdir, ctx):
            return ConfigResult(cfg, "pass")

    res = NoTrace().run(_sv_case(), ctx)
    assert res.status == "error" and "wrote no trace.xtr" in res.reason


def test_tools_captured_before_any_config(ctx):
    class BadTools(Fake):
        def tools(self, ctx):
            raise RuntimeError("simulator missing")

    Fake.calls = []
    res = BadTools().run(_sv_case(), ctx)
    assert res.status == "error" and Fake.calls == []


def test_seeds_record_the_seed_used(ctx, toy, tmp_path):
    import zlib

    py = PythonRunner().run(_case(), ctx)
    assert py.seeds["stimulus"] == zlib.crc32(_case().id.encode())
    seeded = dataclasses.replace(ctx, seed=77)
    PythonRunner().run(_case(), seeded)
    # another runner records the python run's seed, not its own crc32 default
    assert FakeIverilog().run(_case(), ctx).seeds["stimulus"] == 77
    # a frozen .xvec keeps the seed it was generated with
    stim = workdir(ctx, "python", _case().id) / "cfg-init0/stim.xvec"
    case = _tmp_toy(tmp_path, "", source="vectors/frozen.xvec")
    shutil.copy(stim, case.test_dir / "vectors/frozen.xvec")
    assert PythonRunner().run(case, ctx).seeds["stimulus"] == 77


def test_python_timeout_is_error(ctx, toy, tmp_path):
    case = _tmp_toy(
        tmp_path,
        """
        import time

        def gen(ctx):
            time.sleep(5)
            yield from ()
        """,
    )
    res = PythonRunner().run(dataclasses.replace(case, timeout_s=1), ctx)
    assert res.status == "error" and "timeout" in res.reason and "1 s" in res.reason


def test_keyboard_interrupt_cancels_and_writes_partial_summary(ctx, monkeypatch):
    ran: list[str] = []

    class Interrupting(Fake):
        def run(self, case, ctx):
            ran.append(case.id)
            if case.id.endswith(".b"):
                raise KeyboardInterrupt
            return super().run(case, ctx)

    monkeypatch.setitem(RUNNERS, "fake", Interrupting)
    cases = [dataclasses.replace(_sv_case(), id=f"7series.TOYFF.L1.{x}") for x in "abc"]
    with pytest.raises(KeyboardInterrupt):
        run_tests(cases, ["fake"], ctx)
    assert ran == ["7series.TOYFF.L1.a", "7series.TOYFF.L1.b"]  # c was cancelled
    summary = json.loads((ctx.root / "build/rtl/summary.json").read_text())
    assert summary["interrupted"] is True
    assert [r["test_id"] for r in summary["results"]] == ["7series.TOYFF.L1.a"]


def test_result_schema_hw_is_closed():
    import jsonschema

    from xut.runners.base import RunResult

    doc = RunResult("t", "hw", "rtl", "vector", "pass").to_dict()
    doc["hw"] = {"dna": "1", "serial": "2", "site": "3", "extra": "4"}
    with pytest.raises(jsonschema.ValidationError):
        schemas.validate(doc, "result")
    doc["hw"].pop("extra")
    schemas.validate(doc, "result")
