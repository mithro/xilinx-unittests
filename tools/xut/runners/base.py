# SPDX-License-Identifier: Apache-2.0
"""Runner base: one result.json / trace.xtr / run.log per (flow, runner, test) (spec §6, §14).

``Runner.run`` is a template method. Every exit path writes a ``result.json`` that
validates against ``result.schema.json`` (review #9): a declared-unsupported,
unavailable or inapplicable runner writes ``skip`` with the reason; any exception, in a
configuration or outside one, becomes ``error`` with its text (spec §14: a crash or a
timeout is an ``error``, never a ``fail``, and never silently dropped).
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import shutil
import socket
import time
import traceback
import zlib
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar

from xut import schemas
from xut.errors import XutError
from xut.formats import xtr
from xut.modelsrc import ModelSource
from xut.testspec import TestCase, declared

STATUSES = ("pass", "fail", "error", "skip")
_RANK = {"fail": 3, "error": 2, "pass": 1, "skip": 0}
RESULT_FORMAT = "xut-result 1"
#: The per-runner timeout when neither test.yaml ``timeout_s`` nor ``--timeout`` sets one.
DEFAULT_TIMEOUT_S = 600


def worst(statuses: list[str]) -> str:
    """The status of a whole from its parts: ``fail > error > pass > skip`` (an empty
    list is ``skip``). Step 1's PROGRESS marks use the same precedence."""
    return max(statuses, key=_RANK.__getitem__) if statuses else "skip"


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RunContext:
    root: Path
    flow: str
    model_source: ModelSource
    seed: int | None = None
    defines: dict[str, str] = field(default_factory=dict)
    timeout_s: int | None = None
    jobs: int = 1


@dataclass
class ConfigResult:
    cfg: str
    status: str
    reason: str | None = None
    stimulus_sha256: str | None = None
    trace_sha256: str | None = None
    mismatches: int = 0


@dataclass
class RunResult:
    test_id: str
    runner: str
    flow: str
    style: str
    status: str
    reason: str | None = None
    configs: list[ConfigResult] = field(default_factory=list)
    model_source: str | None = None
    seeds: dict = field(default_factory=lambda: {"stimulus": None, "x": []})
    defines: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)
    container: dict | None = None
    duration_s: float = 0.0
    started: str = ""
    host: str = field(default_factory=socket.gethostname)
    x_dependence: bool | None = None
    bins_reached: list[str] | None = None
    hw: dict | None = None

    def to_dict(self) -> dict:
        return {"format": RESULT_FORMAT, **asdict(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1) + "\n"

    def write(self, d: Path) -> None:
        """Validate against ``result.schema.json``, then write ``d/result.json``. A result
        that does not validate raises (and ``Runner.run`` turns that into an error)."""
        data = self.to_dict()
        schemas.validate(data, "result")
        (Path(d) / "result.json").write_text(json.dumps(data, indent=1) + "\n")


def workdir(ctx: RunContext, runner: str, test_id: str) -> Path:
    """``build/<flow>/<runner>/<model-source>/<test-id>``."""
    # The model source is part of the key (review (b) #5): a run against the submodule
    # never overwrites a run against Vivado's UNISIM, and crosscheck can pair like-for-like.
    return ctx.root / "build" / ctx.flow / runner / ctx.model_source.name / test_id


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def seed_for(case: TestCase, ctx: RunContext) -> int:
    """``--seed`` if given, else ``zlib.crc32(test_id)``: stable across runs and hosts."""
    return ctx.seed if ctx.seed is not None else zlib.crc32(case.id.encode())


def timeout_for(case: TestCase, ctx: RunContext) -> int:
    """test.yaml ``timeout_s``, else ``--timeout``, else ``DEFAULT_TIMEOUT_S``."""
    if case.timeout_s is not None:
        return case.timeout_s
    return ctx.timeout_s if ctx.timeout_s is not None else DEFAULT_TIMEOUT_S


# --- the python run is the source of truth for vector tests --------------------------


class NoExpectedTrace(XutError, LookupError):
    """A configuration the python run listed has no ``expected.xtr``."""


def python_dir(ctx: RunContext, case: TestCase) -> Path:
    return workdir(ctx, "python", case.id)


def load_generated(ctx: RunContext, case: TestCase) -> list[tuple[str, Path, Path]]:
    """``(cfg, python cfgdir, expected.xtr)`` for EVERY configuration the python run
    listed in ``configs.json``, errored ones included (their ``expected.xtr`` does not
    exist; ``expected_trace`` explains why). Raises when there is no python run."""
    d = python_dir(ctx, case)
    listing = d / "configs.json"
    if not listing.is_file():
        raise RuntimeError(f"no python run for this test (configs.json missing in {d})")
    return [(c, d / f"cfg-{c}", d / f"cfg-{c}" / "expected.xtr") for c in _read_cfgs(listing)]


def _read_cfgs(listing: Path) -> list[str]:
    cfgs = json.loads(listing.read_text())
    if not (isinstance(cfgs, list) and all(isinstance(c, str) for c in cfgs)):
        raise RuntimeError(f"{listing} is not a list of configuration names")
    return cfgs


def expected_trace(ctx: RunContext, case: TestCase, cfg: str) -> Path:
    """The python run's ``expected.xtr`` for ``cfg``. A missing one raises
    ``NoExpectedTrace("no expected trace (python: <status>: <reason>)")`` (review #10):
    a python failure makes the configuration an error, never drops it."""
    d = python_dir(ctx, case)
    exp = d / f"cfg-{cfg}" / "expected.xtr"
    if exp.is_file():
        return exp
    why = "not run"
    try:
        py = json.loads((d / "result.json").read_text())
        c = next((c for c in py.get("configs", []) if c.get("cfg") == cfg), None)
        if c is not None:
            why = f"{c['status']}: {c.get('reason') or 'no reason recorded'}"
        elif py.get("status") != "pass":
            why = f"{py.get('status')}: {py.get('reason')}"
    except (OSError, ValueError) as e:
        why = f"no readable result.json ({e})"
    raise NoExpectedTrace(f"no expected trace (python: {why})")


# --- the runner template ------------------------------------------------------------


def _reason(e: BaseException) -> str:
    """A ``XutError``'s message is user-facing already; anything else gets its type."""
    text = str(e) if isinstance(e, XutError) else f"{type(e).__name__}: {e}"
    return text.strip() or type(e).__name__


class Runner(ABC):
    name: ClassVar[str]
    x_observable: ClassVar[bool] = True
    styles: ClassVar[frozenset[str]] = frozenset({"vector", "sv", "cocotb"})

    def available(self, ctx: RunContext) -> tuple[bool, str]:
        return True, ""

    def tools(self, ctx: RunContext) -> dict:
        return {}

    def container(self, ctx: RunContext) -> dict | None:
        return None

    def configs(self, case: TestCase, ctx: RunContext) -> list[str]:
        """Configuration names: every config the python run generated (its configs.json,
        errored ones included) for vector tests; test.yaml otherwise. A config without an
        expected trace is NOT dropped: ``expected_trace`` raises ``no expected trace``
        for it, so a python failure can never shrink another runner's matrix (review #10)."""
        if case.style == "vector":
            return [c for c, _, _ in load_generated(ctx, case)]
        return [c["cfg"] for c in case.configs] or ["default"]

    @abstractmethod
    def run_config(self, case: TestCase, cfg: str, cfgdir: Path, ctx: RunContext) -> ConfigResult:
        """Run one configuration in cfgdir; write cfgdir/trace.xtr and cfgdir/run.log."""

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        """Hook for runner-specific aggregate fields (x_dependence, bins_reached)."""
        return None

    def _new_result(
        self, case: TestCase, ctx: RunContext, status: str, reason: str | None
    ) -> RunResult:
        return RunResult(
            case.id,
            self.name,
            ctx.flow,
            case.style,
            status,
            reason,
            model_source=ctx.model_source.name,
            defines=dict(ctx.defines),
            started=_now(),
        )

    def _skip(self, case: TestCase, ctx: RunContext, d: Path, reason: str) -> RunResult:
        r = self._new_result(case, ctx, "skip", reason)
        (d / "run.log").write_text(f"skip: {reason}\n")
        r.write(d)
        return r

    def run(self, case: TestCase, ctx: RunContext) -> RunResult:
        """Template method. Every exit path writes result.json (spec §14, review #9):
        any exception outside run_config becomes an ``error`` result with the traceback."""
        d = workdir(ctx, self.name, case.id)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        t0 = time.monotonic()
        try:
            return self._run(case, ctx, d)
        except Exception as e:
            return error_result(case, self.name, ctx, e, d, time.monotonic() - t0)

    def _run(self, case: TestCase, ctx: RunContext, d: Path) -> RunResult:
        ok, why = declared(case, self.name)
        if not ok:
            return self._skip(case, ctx, d, f"declared unsupported: {why}")
        if case.style not in self.styles:
            return self._skip(case, ctx, d, f"runner {self.name} does not run {case.style} tests")
        ok, why = self.available(ctx)
        if not ok:
            return self._skip(case, ctx, d, f"runner unavailable: {why}")
        t0 = time.monotonic()
        res = self._new_result(case, ctx, "skip", None)
        res.seeds["stimulus"] = seed_for(case, ctx)
        parts: list[tuple[str, xtr.Trace]] = []
        logs: list[str] = []
        cfgs = self.configs(case, ctx)
        if not cfgs:
            res.status, res.reason = "error", "no configurations (did the python runner fail?)"
        excluded = case.config_exclusions.get(self.name, {})
        for cfg in cfgs:
            cd = d / f"cfg-{cfg}"
            cd.mkdir()
            pat = next((g for g in excluded if fnmatch.fnmatchcase(cfg, g)), None)
            if pat is not None:  # declared per-configuration exclusion: skip, with reason
                cr = ConfigResult(cfg, "skip", f"excluded: {excluded[pat]}")
                res.configs.append(cr)
                logs.append(f"===== cfg {cfg}: skip {cr.reason}\n")
                continue
            try:
                cr = self.run_config(case, cfg, cd, ctx)
            except Exception as e:  # recorded as error with the traceback in the log
                with (cd / "run.log").open("a") as f:
                    f.write(traceback.format_exc())
                cr = ConfigResult(cfg, "error", _reason(e))
            if (cd / "trace.xtr").is_file():
                try:
                    parts.append((cfg, xtr.load(cd / "trace.xtr")))
                except xtr.XtrError as e:
                    cr = ConfigResult(cfg, "error", f"malformed trace.xtr: {e}")
            res.configs.append(cr)
            log = (cd / "run.log").read_text() if (cd / "run.log").is_file() else ""
            logs.append(f"===== cfg {cfg}: {cr.status} {cr.reason or ''}\n" + log)
        if res.configs:
            res.status = worst([c.status for c in res.configs])
            # fail/error name their failing configs; an all-skip result names its skips
            why = [c for c in res.configs if c.status == res.status and c.status != "pass"]
            res.reason = "; ".join(f"{c.cfg}: {c.reason}" for c in why[:5]) or None
            if len(why) > 5:
                res.reason += f"; ... ({len(why) - 5} more)"
        header = {
            "runner": self.name,
            "flow": ctx.flow,
            "model": ctx.model_source.name,
            "seed": str(res.seeds["stimulus"]),
            "prim": case.prim,
            "test": case.id,
        }
        if case.style == "vector" and self.name == "python":
            header.update(model="golden", kind="expected")
        xtr.dump(xtr.concat(parts, header), d / "trace.xtr")
        (d / "run.log").write_text("".join(logs))
        res.tools, res.container = self.tools(ctx), self.container(ctx)
        self.finish(case, ctx, d, res)
        res.duration_s = round(time.monotonic() - t0, 3)
        res.write(d)
        return res


def error_result(
    case: TestCase,
    runner: str,
    ctx: RunContext,
    e: BaseException,
    d: Path | None = None,
    duration_s: float = 0.0,
) -> RunResult:
    """Write (and return) an ``error`` result.json for ``e``, with its traceback appended
    to run.log. Used by ``Runner.run`` and by ``xut.run`` for a runner that cannot even
    be constructed: every selected (test, runner) pair ends with a result.json."""
    d = d or workdir(ctx, runner, case.id)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "run.log").open("a") as f:
        f.write("".join(traceback.format_exception(e)))
    r = RunResult(
        case.id,
        runner,
        ctx.flow,
        case.style,
        "error",
        _reason(e),
        model_source=ctx.model_source.name,
        defines=dict(ctx.defines),
        duration_s=round(duration_s, 3),
        started=_now(),
    )
    r.write(d)
    return r
