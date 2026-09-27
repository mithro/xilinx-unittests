# SPDX-License-Identifier: Apache-2.0
"""Which CI work a change needs (``.github/workflows/ci.yml``, the ``changes`` job).

Fail-safe by construction: the ``sim`` job's container build, container pytest and flops
runs are skipped only when there is positive evidence that nothing they read changed:

- the event is a ``pull_request`` (a push to ``main`` always runs everything);
- the changed files could be listed (``git diff --name-only <base>...HEAD`` succeeded);
- the list is not empty, and **every** file matches ``DOC_ONLY``: progress logs,
  specs/plans, and the top-level ``README.md``/``AGENTS.md``. No container test or flops
  run reads any of them (the tooling job, which always runs in full, still lints them).

Anything else (a new or unknown path, ``docs/work-units.yaml``, ``docs/templates/**``,
a git error, an empty list) runs everything. The ``sim`` job itself always runs, so its
check is reported on every PR; when nothing needs it, its only step says so.

Stdlib only: the ``changes`` job runs it with the runner's ``python3`` before ``uv sync``.
Dry run: ``python3 tools/xut/ci_select.py --event pull_request --files docs/x.md tools/y.py``.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Sequence

#: Paths that no sim-job step reads (fnmatch; ``*`` also matches ``/``).
DOC_ONLY = ("log/*.md", "docs/superpowers/*", "README.md", "AGENTS.md")


def doc_only(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in DOC_ONLY)


def select(event: str, files: Sequence[str] | None) -> tuple[bool, str]:
    """``(sim needed, why)`` for ``event`` and the changed ``files`` (None: unknown)."""
    if event != "pull_request":
        return True, f"event {event!r}: everything runs"
    if files is None:
        return True, "the changed files could not be listed: everything runs"
    if not files:
        return True, "no changed files listed: everything runs"
    other = [f for f in files if not doc_only(f)]
    if other:
        return True, f"{len(other)} non-doc file(s) changed, e.g. {other[0]}: everything runs"
    return False, f"all {len(files)} changed file(s) are docs/logs only: sim steps skipped"


def changed_files(base: str) -> list[str] | None:
    """``git diff --name-only <base>...HEAD`` (renames: both sides), or None on error."""
    p = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...HEAD"],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        print(f"git diff failed ({p.returncode}): {p.stderr.strip()}", file=sys.stderr)
        return None
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", required=True)
    ap.add_argument("--base", help="the PR's base ref, e.g. origin/main")
    ap.add_argument("--files", nargs="*", help="dry run: these changed files, no git")
    a = ap.parse_args(argv)
    if a.files is not None:
        files: list[str] | None = a.files
    elif a.event == "pull_request" and a.base:
        files = changed_files(a.base)
    else:
        files = None
    sim, why = select(a.event, files)
    print(f"sim={'true' if sim else 'false'}: {why}")
    for f in files or []:
        print(f"  {'doc ' if doc_only(f) else 'code'} {f}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"sim={'true' if sim else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
