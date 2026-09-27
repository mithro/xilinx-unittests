# SPDX-License-Identifier: Apache-2.0
"""A host-wide limit on concurrent Vivado runs (AGENTS.md: at most 4 at a time; PR #10 CQ2).

``vivado_slot()`` is a context manager that holds one of ``XUT_VIVADO_SLOTS`` (default 4)
slots for its body. A slot is an exclusive ``flock`` on ``slot<i>.lock`` in
``$XDG_RUNTIME_DIR/xut-vivado/`` (``<tmp>/xut-<uid>/xut-vivado/`` without it): it scans the
slots without blocking and takes the first free one, and when every slot is held it waits,
scanning again every ``POLL_S``. ``flock`` locks belong to an open file description, so the
limit holds across processes and across threads of one process alike, and the kernel
releases a slot when its holder dies.

Every host Vivado invocation takes one: the xsim runner's and the equivalence oracle's
``xsim.run_script``, and ``xsim.xsim_version``.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from xut.errors import XutError

SLOTS_ENV = "XUT_VIVADO_SLOTS"
DEFAULT_SLOTS = 4
POLL_S = 0.5


def slot_dir() -> Path:
    """``$XDG_RUNTIME_DIR/xut-vivado`` (``<tmp>/xut-<uid>/xut-vivado`` without it)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or str(
        Path(tempfile.gettempdir()) / f"xut-{os.getuid()}"
    )
    return Path(base) / "xut-vivado"


def slot_count() -> int:
    """``$XUT_VIVADO_SLOTS`` (default 4); ``XutError`` unless it is a positive integer."""
    raw = os.environ.get(SLOTS_ENV, str(DEFAULT_SLOTS))
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n < 1:
        raise XutError(f"${SLOTS_ENV}={raw!r} is not a positive integer")
    return n


@contextmanager
def vivado_slot(
    n: int | None = None,
    lock_dir: Path | None = None,
    *,
    poll_s: float = POLL_S,
    log: Callable[[str], None] | None = None,
) -> Iterator[int]:
    """Hold one of ``n`` (``slot_count()``) slots in ``lock_dir`` (``slot_dir()``) for the
    body; yields the slot's index. ``log`` is told once when every slot is busy."""
    n = slot_count() if n is None else n
    if n < 1:
        raise XutError(f"vivado_slot: {n} slots")
    d = Path(lock_dir) if lock_dir is not None else slot_dir()
    d.mkdir(parents=True, exist_ok=True)
    waited = False
    while True:
        for i in range(n):
            f = (d / f"slot{i}.lock").open("a")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            try:
                yield i
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
            return
        if not waited and log is not None:
            log(f"vivado_slot: all {n} slots in {d} are busy; waiting")
        waited = True
        time.sleep(poll_s)
