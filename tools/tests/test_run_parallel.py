# SPDX-License-Identifier: Apache-2.0
"""xut.run: configurations as units of work (ruling S61), on fake runners."""

import dataclasses
import json
import threading
import time
from pathlib import Path

import pytest

from xut import run as run_mod
from xut.modelsrc import ModelSource
from xut.runners import RUNNERS
from xut.runners.base import ConfigResult, RunContext, Runner, workdir
from xut.testspec import TestCase, discover

FIX = Path(__file__).parent / "fixtures"
CFGS = [f"c{i}" for i in range(8)]


def _case(level: str = "L1", name: str = "par", cfgs: list[str] = CFGS) -> TestCase:
    base = next(c for c in discover(FIX) if c.id == "7series.TOYFF.L1.sv_basic")
    return dataclasses.replace(
        base,
        id=f"7series.TOYFF.{level}.{name}",
        level=level,
        configs=[{"cfg": c} for c in cfgs],
        runners={**base.runners, "fake": "yes", "fakehost": "yes", "fakeseq": "yes"},
    )


class _Probe:
    """Counts concurrent run_config calls per pool kind."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active: dict[str, int] = {}
        self.peak: dict[str, int] = {}
        self.order: list[str] = []

    def enter(self, kind: str, what: str) -> None:
        with self.lock:
            self.active[kind] = self.active.get(kind, 0) + 1
            self.peak[kind] = max(self.peak.get(kind, 0), self.active[kind])
            self.order.append(what)

    def leave(self, kind: str) -> None:
        with self.lock:
            self.active[kind] -= 1


PROBE = _Probe()


class Fake(Runner):
    """Each configuration fails with its own name as the reason; later configurations
    finish first (a longer sleep for earlier ones)."""

    name = "fake"
    kind = "container"

    def run_config(self, case, cfg, cd, ctx):
        PROBE.enter(self.kind, f"{case.id}/{cfg}")
        try:
            time.sleep(0.02 * (len(CFGS) - CFGS.index(cfg)) if cfg in CFGS else 0.01)
            (cd / "run.log").write_text(f"ran {cfg}\n")
            return ConfigResult(cfg, "fail", f"reason {cfg}")
        finally:
            PROBE.leave(self.kind)


class FakeHost(Fake):
    name = "fakehost"
    kind = "host"


class FakeSeq(Fake):
    name = "fakeseq"
    kind = "seq"
    parallel_configs = False


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    global PROBE
    PROBE = _Probe()
    for cls in (Fake, FakeHost, FakeSeq):
        monkeypatch.setitem(RUNNERS, cls.name, cls)
    monkeypatch.setattr(run_mod, "HOST_RUNNERS", ("fakehost",))
    monkeypatch.setenv("XUT_XSIM_SLOTS", "3")
    return RunContext(tmp_path, "rtl", ModelSource("m", tmp_path), jobs=2)


def test_results_and_logs_keep_configuration_order(fakes):
    """Configurations finish in reverse; result.json and run.log keep the configuration
    order, and equal what the sequential template (Runner.run) writes."""
    case = _case()
    (res,) = run_mod.run_tests([case], ["fake"], fakes)
    assert [c.cfg for c in res.configs] == CFGS
    assert [c.reason for c in res.configs] == [f"reason {c}" for c in CFGS]
    d = workdir(fakes, "fake", case.id)
    par = json.loads((d / "result.json").read_text())
    par_log = (d / "run.log").read_text()
    assert [ln for ln in par_log.splitlines() if ln.startswith("=====")] == [
        f"===== cfg {c}: fail reason {c}" for c in CFGS
    ]
    seq = Fake().run(case, fakes)  # the sequential template, same directory
    seq_json = json.loads((d / "result.json").read_text())
    for k in ("started", "duration_s"):
        par.pop(k), seq_json.pop(k)
    assert par == seq_json and (d / "run.log").read_text() == par_log
    assert seq.status == res.status == "fail"


def test_configurations_run_concurrently_within_jobs(fakes):
    """A pair's configurations spread over the workers, and never more than --jobs at
    once (each may hold one container)."""
    run_mod.run_tests([_case(), _case("L2", "two")], ["fake"], fakes)
    assert PROBE.peak["container"] == 2  # jobs=2: both workers busy, never more


def test_host_runner_uses_its_own_pool(fakes):
    """The host runner's configurations run in the host pool (min(jobs, xsim slots)),
    beside the container pool."""
    ctx = dataclasses.replace(fakes, jobs=4)
    run_mod.run_tests([_case()], ["fakehost", "fake"], ctx)
    assert PROBE.peak["host"] == 3  # min(4, XUT_XSIM_SLOTS=3)
    assert PROBE.peak["container"] <= 4


def test_stateful_runner_runs_whole_in_order(fakes):
    run_mod.run_tests([_case()], ["fakeseq"], fakes)
    assert PROBE.peak["seq"] == 1
    assert [w.split("/")[1] for w in PROBE.order] == CFGS


def test_pairs_start_highest_level_first(fakes):
    ctx = dataclasses.replace(fakes, jobs=1)
    cases = [_case("L0", "a", ["x"]), _case("L2", "b", ["y"]), _case("L1", "c", ["z"])]
    res = run_mod.run_tests(cases, ["fake"], ctx)
    assert [w.split("/")[1] for w in PROBE.order] == ["y", "z", "x"]
    assert [r.test_id for r in res] == [c.id for c in cases]  # selection order kept


def test_schedule_is_stable():
    l0, l2 = _case("L0", "a"), _case("L2", "b")
    pairs = [(l0, "x"), (l2, "x"), (l0, "y"), (l2, "y")]
    assert run_mod.schedule(pairs) == [1, 3, 0, 2]


def test_a_runner_that_cannot_be_constructed_is_an_error(fakes, monkeypatch):
    class Broken(Fake):
        def __init__(self):
            raise RuntimeError("no")

    monkeypatch.setitem(RUNNERS, "fake", Broken)
    (res,) = run_mod.run_tests([_case()], ["fake"], fakes)
    assert res.status == "error" and "RuntimeError: no" in res.reason


def test_an_exception_outside_run_config_errors_the_pair(fakes, monkeypatch):
    """As the sequential loop: an exception outside run_config (here: the cfg directory
    already exists) makes the whole result an error."""
    real = Runner._run_cfg

    def boom(self, plan, cfg):
        if cfg == "c3":
            raise OSError("disk on fire")
        return real(self, plan, cfg)

    monkeypatch.setattr(Runner, "_run_cfg", boom)
    (res,) = run_mod.run_tests([_case()], ["fake"], fakes)
    assert res.status == "error" and "disk on fire" in res.reason


def test_keyboard_interrupt_cancels_and_kills(fakes, monkeypatch):
    """A KeyboardInterrupt in a configuration stops the run: queued work is cancelled,
    running containers are killed, an interrupted summary is written, and it propagates."""
    killed = []
    monkeypatch.setattr("xut.container.kill_live", lambda: killed.append(True))

    def interrupt(self, case, cfg, cd, ctx):
        if cfg == "c1":
            raise KeyboardInterrupt
        time.sleep(0.05)
        return ConfigResult(cfg, "fail", "x")

    monkeypatch.setattr(Fake, "run_config", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_mod.run_tests([_case(), _case("L0", "b")], ["fake"], fakes)
    summary = json.loads(run_mod.summary_path(fakes).read_text())
    assert summary["interrupted"] is True and killed == [True]


def test_a_pair_is_written_as_soon_as_its_own_configurations_are_done(fakes, monkeypatch):
    """Correctness review of #25: a pair's result (result.json, progress, an interrupt's
    record) never waits for other pairs' configurations: B's last configuration waits
    until A's result.json exists (or 5 s) and records whether it did."""
    a, b = _case("L1", "a", ["x"]), _case("L1", "b", ["y0", "y1", "y2", "y3"])
    seen: dict[str, bool] = {}
    a_result = workdir(fakes, "fake", a.id) / "result.json"

    def cfg(self, case, cfg, cd, ctx):
        if case.id == b.id and cfg == "y3":
            deadline = time.monotonic() + 5
            while not a_result.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            seen["a written"] = a_result.is_file()
        return ConfigResult(cfg, "fail", f"reason {cfg}")

    monkeypatch.setattr(Fake, "run_config", cfg)
    # one worker: A's end must not queue behind B's configurations
    res = run_mod.run_tests([a, b], ["fake"], dataclasses.replace(fakes, jobs=1))
    assert seen == {"a written": True}
    assert [r.test_id for r in res] == [a.id, b.id]


def test_sequential_run_stops_at_the_first_exception_outside_run_config(fakes, monkeypatch):
    """Runner.run keeps the old loop's behaviour: no configuration runs after one raised
    outside run_config (review nit), and the pair is an error."""
    real = Runner._run_cfg
    ran: list[str] = []

    def boom(self, plan, cfg):
        ran.append(cfg)
        if cfg == "c2":
            raise OSError("disk on fire")
        return real(self, plan, cfg)

    monkeypatch.setattr(Runner, "_run_cfg", boom)
    res = Fake().run(_case(), fakes)
    assert ran == ["c0", "c1", "c2"]
    assert res.status == "error" and "disk on fire" in res.reason
