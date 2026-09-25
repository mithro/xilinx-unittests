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
from concurrent.futures import ThreadPoolExecutor

from xut import runners as runner_registry
from xut.errors import XutError
from xut.runners.base import RunContext, RunResult, error_result
from xut.testspec import TestCase


def _one(case: TestCase, name: str, ctx: RunContext) -> RunResult:
    try:
        runner = runner_registry.RUNNERS[name]()
    except Exception as e:  # even a runner that cannot start leaves a result.json
        return error_result(case, name, ctx, e)
    return runner.run(case, ctx)


def run_tests(cases: list[TestCase], runner_names: list[str], ctx: RunContext) -> list[RunResult]:
    """Run every selected runner on every case; the results, python runs first."""
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

    results = [tick(_one(c, n, ctx)) for c, n in first]
    with ThreadPoolExecutor(max_workers=max(1, ctx.jobs)) as pool:
        futures = [pool.submit(lambda c=c, n=n: tick(_one(c, n, ctx))) for c, n in rest]
        results += [f.result() for f in futures]
    write_summary(results, ctx)
    return results


def write_summary(results: list[RunResult], ctx: RunContext) -> None:
    out = ctx.root / "build" / ctx.flow / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format": "xut-summary 1",
        "flow": ctx.flow,
        "model_source": ctx.model_source.name,
        "results": [
            {"test_id": r.test_id, "runner": r.runner, "status": r.status, "reason": r.reason}
            for r in results
        ],
    }
    out.write_text(json.dumps(data, indent=1) + "\n")
