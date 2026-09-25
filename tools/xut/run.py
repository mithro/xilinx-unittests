# SPDX-License-Identifier: Apache-2.0
"""``xut run``: run (test, runner) pairs and write build/<flow>/summary.json.

The python run is the source of truth for vector tests, so ``python`` always runs first
(sequentially: the model is fast) for every selected vector test, whichever runners
were selected. The remaining pairs run in a thread pool of ``ctx.jobs`` workers; the
simulators themselves are subprocesses. A ``progress: done=N total=M elapsed_s=E`` line
is printed after every completion, for long-run monitors.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from xut import runners as runner_registry
from xut.errors import XutError
from xut.runners.base import RunContext, RunResult, error_result
from xut.testspec import TestCase


class _Cancelled(Exception):
    """A queued run not started because the invocation was interrupted."""


def _one(case: TestCase, name: str, ctx: RunContext) -> RunResult:
    """Run one pair. Last line of defence: ``Runner.run`` already turns every exception
    into an error result.json, but a runner that cannot be constructed, or a bug in a
    subclass's ``run``, must not abort the whole invocation either."""
    try:
        return runner_registry.RUNNERS[name]().run(case, ctx)
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


def run_tests(cases: list[TestCase], runner_names: list[str], ctx: RunContext) -> list[RunResult]:
    """Run every selected runner on every case; the results, python runs first.

    On KeyboardInterrupt, queued jobs are cancelled, running ones finish, summary.json
    records what completed, and the KeyboardInterrupt propagates (the CLI exits 130)."""
    known = runner_registry.RUNNERS
    names = list(dict.fromkeys(runner_names))
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
    try:
        for c, n in first:
            results.append(job(c, n))
        futures = [pool.submit(job, c, n) for c, n in rest]
        for f in futures:
            f.result()  # in order; re-raises a KeyboardInterrupt from a worker
    except KeyboardInterrupt:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        results += [f.result() for f in futures if not f.cancelled() and f.exception() is None]
        write_summary(results, ctx, interrupted=True)
        raise
    results += [f.result() for f in futures]
    pool.shutdown(wait=True)
    write_summary(results, ctx)
    return results


def write_summary(results: list[RunResult], ctx: RunContext, interrupted: bool = False) -> None:
    out = ctx.root / "build" / ctx.flow / "summary.json"
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
