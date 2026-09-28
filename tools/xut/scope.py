# SPDX-License-Identifier: Apache-2.0
"""Capped scopes for heavy commands (AGENTS.md §10.1, memory safety).

``scoped_run`` runs a command in its own transient systemd user scope::

    systemd-run --user --scope --quiet --slice=vivado.slice --unit=xut-<what>-<t>-<pid>-<r>
        -p MemoryMax=<cap> -p MemorySwapMax=0 -- <argv>

so an OOM kill stays inside it. With no systemd-run it refuses: a heavy command never
falls back to an unscoped run. The host-wide bound on concurrent Vivado/xsim processes
is PR #10's ``xut.slots.vivado_slot()`` (ruling S50 CQ2); every caller takes a slot
around its ``scoped_run``.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from xut.container import RunTimeout
from xut.errors import XutError

VIVADO_MEMORY_MAX = "16G"
#: A process killed by the OOM killer: bash reports 137, a direct child -9.
OOM_RCS = (137, -9)
_KILL_GRACE_S = 30


class ScopeError(XutError, RuntimeError):
    """A heavy command cannot run in a capped scope."""


def scope_argv(argv: Sequence[str], what: str, memory_max: str) -> list[str]:
    unit = f"xut-{what}-{int(time.time())}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--slice=vivado.slice",
        f"--unit={unit}",
        "-p",
        f"MemoryMax={memory_max}",
        "-p",
        "MemorySwapMax=0",
        "--",
        *argv,
    ]


def scoped_run(
    argv: Sequence[str],
    *,
    what: str,
    memory_max: str,
    cwd: Path,
    log: Path,
    timeout_s: int,
) -> int:
    """Run ``argv`` in a capped scope, appending its output to ``log``; its exit code."""
    if shutil.which("systemd-run") is None:
        raise ScopeError(
            "systemd-run not found: heavy commands run only in a capped scope "
            "(AGENTS.md §10.1); refusing to run unscoped"
        )
    return run_in_group(scope_argv(argv, what, memory_max), cwd=cwd, log=log, timeout_s=timeout_s)


def run_in_group(
    argv: Sequence[str], *, cwd: Path, log: Path, timeout_s: int, mode: str = "a"
) -> int:
    """``argv`` in its own process group, stdout and stderr to ``log`` (opened with
    ``mode``); its exit code. On a timeout the whole group is killed (the tools a script
    starts too) and ``RunTimeout`` is raised. The one implementation: ``scoped_run`` and
    ``xut.runners.xsim.run_script`` both use it."""
    with Path(log).open(mode) as f:
        p = subprocess.Popen(
            argv, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=_KILL_GRACE_S)
            raise RunTimeout(f"timeout after {timeout_s}s: {' '.join(argv[:3])}") from e


_VERSIONS: dict[str, str] = {}
_VERSIONS_LOCK = threading.Lock()


def cached_version(key: str, probe: Callable[[], str]) -> str:
    """``probe()`` once per process per ``key`` (a tool's version line). The one cache:
    ``xut.runners.xsim.xsim_version`` uses it, and so does the Vivado builder (Task 6).
    A probe that raises caches nothing."""
    with _VERSIONS_LOCK:
        if key not in _VERSIONS:
            _VERSIONS[key] = probe()
        return _VERSIONS[key]
