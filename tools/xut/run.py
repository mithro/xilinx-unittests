# SPDX-License-Identifier: Apache-2.0
"""``xut run``: run (test, runner) pairs and write build/<flow>/summary-<model-source>.json.

The python run is the source of truth for vector tests, so ``python`` always runs first
(sequentially: the model is fast) for every selected vector test, whichever runners
were selected.

**The remaining pairs run configuration by configuration** (ruling S61). A pair's
configurations are independent (each writes only its own ``cfg-<cfg>/``), so each is its
own unit of work. A pair is three kinds of task (``Runner.begin``, ``Runner.run_cfg`` per
configuration, ``Runner.end``); no task ever waits for another, so there is no deadlock.
``duration_s`` is the pair's wall time from ``begin`` to ``end``, which includes the time
its configurations waited in the queue behind other pairs':

- ``begin`` (the tool versions, the configuration list) runs in the main pool of
  ``ctx.jobs`` workers; ``end`` (the aggregation, in configuration order whatever order
  the configurations finished in; no container) runs in the thread that finished the
  pair's last configuration, so each pair is written, reported (``progress:``) and kept
  on an interrupt as soon as its own configurations are done;
- each configuration runs in the main pool, or, for xsim (``HOST_RUNNERS``), in the host
  pool of ``min(ctx.jobs, xsim slots)`` workers: xsim runs on the host, holding one xsim
  slot and no container, so it never takes a worker a container runner could use.

A task holds at most one container at a time, so at most ``ctx.jobs`` containers run at
once, as before (``--jobs`` is the container budget, AGENTS.md §10.1). A runner that keeps
per-test state on ``self`` (``parallel_configs = False``: ``PythonRunner``) or overrides
``run`` runs whole, as one task. The pairs are started highest level first (``schedule``:
L3 to L0, the L2 tests having the most configurations); a pair's configurations are queued
when its ``begin`` task has run. Results, the summary and the printed table keep the
selection order.

A ``progress: done=N total=M elapsed_s=E`` line is printed after every finished pair, for
long-run monitors.

Selecting ``verilator`` also selects ``iverilog-vz`` (``with_companions``): Icarus on the
verilatorized models guards every Verilator result (spec §6.2).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from xut import runners as runner_registry
from xut.errors import XutError
from xut.runners.base import CfgOutcome, RunContext, Runner, RunResult, error_result
from xut.testspec import TestCase


class _Cancelled(Exception):
    """A queued run not started because the invocation was interrupted."""


#: Runners whose configurations run in the host pool (module docstring).
HOST_RUNNERS = ("xsim",)
_LEVEL_RANK = {"L3": 0, "L2": 1, "L1": 2, "L0": 3}


def schedule(pairs: list[tuple[TestCase, str]]) -> list[int]:
    """The indices of ``pairs`` in start order: highest level first; stable, so ties keep
    their selection order."""
    return sorted(
        range(len(pairs)), key=lambda i: _LEVEL_RANK.get(pairs[i][0].level, len(_LEVEL_RANK))
    )


def host_workers(ctx: RunContext) -> int:
    """The host pool's size: ``ctx.jobs``, at most the host's xsim slots."""
    from xut import slots

    return max(1, min(ctx.jobs, slots.slot_count("xsim")))


def _whole(runner: Runner) -> bool:
    """``runner`` runs as one task: it keeps per-test state, or overrides ``run``."""
    return not runner.parallel_configs or type(runner).run is not Runner.run


def _one(case: TestCase, name: str, ctx: RunContext) -> RunResult:
    """Run one pair. Last line of defence: ``Runner.run`` already turns every exception
    into an error result.json, but a runner that cannot be constructed, or a bug in a
    subclass's ``run``, must not abort the whole invocation either."""
    return _guarded(case, name, ctx, lambda: runner_registry.RUNNERS[name]().run(case, ctx))


def _guarded[R](case: TestCase, name: str, ctx: RunContext, fn: Callable[[], R]) -> R | RunResult:
    """``fn()``; any exception becomes the pair's error result (``_one``'s fallbacks)."""
    try:
        return fn()
    except Exception as e:
        try:
            return error_result(case, name, ctx, e)
        except Exception as e2:  # not even result.json could be written: say so
            return RunResult(
                case.id,
                name,
                ctx.flow,
                case.style,
                "error",
                f"{type(e).__name__}: {e}; and result.json could not be written: "
                f"{type(e2).__name__}: {e2}",
                model_source=ctx.model_source.name,
            )


#: runner -> the runners that must run whenever it does
COMPANIONS = {"verilator": ("iverilog-vz",)}


def with_companions(names: list[str]) -> list[str]:
    """``names`` (deduplicated, in order) plus each selected runner's companions."""
    out = list(dict.fromkeys(names))
    for n in list(out):
        out += [c for c in COMPANIONS.get(n, ()) if c not in out]
    return out


def run_tests(cases: list[TestCase], runner_names: list[str], ctx: RunContext) -> list[RunResult]:
    """Run every selected runner on every case; the results, python runs first.

    On KeyboardInterrupt, queued jobs are cancelled, running containers are killed
    (``xut.container.kill_live``), the summary records what completed before that, and
    the KeyboardInterrupt propagates (the CLI exits 130)."""
    known = runner_registry.RUNNERS
    names = with_companions(runner_names)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise XutError(f"unknown runner(s) {unknown} (known: {sorted(known)})")
    first = [(c, "python") for c in cases if c.style == "vector"] if names else []
    rest = [(c, n) for c in cases for n in names if not (n == "python" and c.style == "vector")]
    total = len(first) + len(rest)
    t0 = time.monotonic()
    done = 0
    lock = threading.Lock()

    def tick(r: RunResult) -> RunResult:
        nonlocal done
        with lock:
            done += 1
            print(
                f"progress: done={done} total={total} elapsed_s={time.monotonic() - t0:.1f}"
                f"  {r.test_id} {r.runner}: {r.status}",
                flush=True,
            )
        return r

    stop = threading.Event()

    def job(c: TestCase, n: str) -> RunResult:
        if stop.is_set():  # interrupted: never start another run
            raise _Cancelled
        try:
            return tick(_one(c, n, ctx))
        except KeyboardInterrupt:
            stop.set()
            raise

    results: list[RunResult] = []
    futures: list[Future[RunResult]] = []
    pool = ThreadPoolExecutor(max_workers=max(1, ctx.jobs))
    host = ThreadPoolExecutor(max_workers=host_workers(ctx))
    pools = (pool, host)

    def task(fut: Future[RunResult], body: Callable[[], None]) -> Callable[[], None]:
        """``body`` as a pool task: an interrupted invocation never starts it, and anything
        it raises ends the pair's future instead of vanishing in the pool."""

        def run() -> None:
            try:
                if stop.is_set():
                    raise _Cancelled
                body()
            except BaseException as e:
                if not fut.done():
                    fut.set_exception(e)
                if isinstance(e, KeyboardInterrupt):
                    stop.set()
                    raise

        return run

    def start(c: TestCase, n: str, fut: Future[RunResult]) -> None:
        """The pair's ``begin`` task: queue its configurations (or run it whole)."""
        runner = _guarded(c, n, ctx, lambda: runner_registry.RUNNERS[n]())
        if isinstance(runner, RunResult):  # the runner cannot even be constructed
            fut.set_result(tick(runner))
            return
        if _whole(runner):
            fut.set_result(tick(_guarded(c, n, ctx, lambda: runner.run(c, ctx))))
            return
        plan = _guarded(c, n, ctx, lambda: runner.begin(c, ctx))
        if isinstance(plan, RunResult):  # a skip or an error: nothing to run
            fut.set_result(tick(plan))
            return
        outs: list[CfgOutcome | None] = [None] * len(plan.cfgs)
        left = [len(plan.cfgs)]
        guard = threading.Lock()

        def finish() -> None:
            done = [o for o in outs if o is not None]
            fut.set_result(tick(_guarded(c, n, ctx, lambda: runner.end(plan, done))))

        def one(j: int, cfg: str) -> None:
            outs[j] = runner.run_cfg(plan, cfg)
            with guard:
                left[0] -= 1
                last = left[0] == 0
            if last:  # inline: queued behind every other configuration, the pair would
                finish()  # finish only when the whole run did (correctness review of #25)

        if not plan.cfgs:
            finish()
            return
        target = host if n in HOST_RUNNERS else pool
        for j, cfg in enumerate(plan.cfgs):
            target.submit(task(fut, lambda j=j, cfg=cfg: one(j, cfg)))

    try:
        for c, n in first:
            results.append(job(c, n))
        pair_futs: dict[int, Future[RunResult]] = {}
        for i in schedule(rest):
            fut: Future[RunResult] = Future()
            fut.set_running_or_notify_cancel()
            pair_futs[i] = fut
            c, n = rest[i]
            pool.submit(task(fut, lambda c=c, n=n, fut=fut: start(c, n, fut)))
        futures = [pair_futs[i] for i in range(len(rest))]  # results in selection order
        for f in futures:
            f.result()  # in order; re-raises a KeyboardInterrupt from a worker
    except (KeyboardInterrupt, _Cancelled) as e:
        # _Cancelled: a pair stopped because a worker's KeyboardInterrupt set ``stop``
        # before this loop reached that worker's pair: the same interrupt
        stop.set()
        for p in pools:
            p.shutdown(wait=False, cancel_futures=True)
        # S48a M-1: kill the running containers rather than wait for them; a killed run's
        # result is an artefact of the kill, so only runs done before it are recorded
        finished = [f for f in futures if f.done()]
        from xut import container

        container.kill_live()
        for p in pools:
            p.shutdown(wait=True)
        results += [f.result() for f in finished if not f.cancelled() and f.exception() is None]
        write_summary(results, ctx, interrupted=True)
        if isinstance(e, _Cancelled):
            raise KeyboardInterrupt from e
        raise
    results += [f.result() for f in futures]
    for p in pools:
        p.shutdown(wait=True)
    write_summary(results, ctx)
    return results


def summary_path(ctx: RunContext) -> Path:
    """``build/<flow>/summary-<model-source>.json``: keyed by model source like every
    result directory, so a run against another model source never overwrites it."""
    return ctx.root / "build" / ctx.flow / f"summary-{ctx.model_source.name}.json"


def write_summary(results: list[RunResult], ctx: RunContext, interrupted: bool = False) -> None:
    out = summary_path(ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "xut-summary 1",
        "flow": ctx.flow,
        "model_source": ctx.model_source.name,
        "interrupted": interrupted,
        "results": [
            {"test_id": r.test_id, "runner": r.runner, "status": r.status, "reason": r.reason}
            for r in results
        ],
    }
    out.write_text(json.dumps(data, indent=1) + "\n")
