# SPDX-License-Identifier: Apache-2.0
"""Host-wide limits on concurrent Vivado tool runs (AGENTS.md §10.1; PR #10 CQ2; ruling
S60), one pool per kind of run:

- ``kind="vivado"``: Vivado synthesis and implementation (``xut hw build``), at most
  ``XUT_VIVADO_SLOTS`` (default 4) at a time, each sized at 16G;
- ``kind="xsim"``: the xsim simulator (xvlog, xelab and the simulation of one
  configuration): the xsim runner's and the equivalence oracle's ``xsim.run_script`` and
  ``xsim.xsim_version``, at most ``XUT_XSIM_SLOTS`` (default 12) at a time. An xsim run is
  small: one configuration's whole ``xsim.sh`` peaked at 340M alone (``xsim -R``), and a
  unit run with four at once peaked at 1.3G for its whole scope (255M with the standalone
  run), so 12 fit in well under 5G.

``vivado_slot()`` is a context manager that holds one slot of its kind for its body. A
slot is an exclusive ``flock`` on ``slot<i>.lock`` in the kind's directory under
``$XDG_RUNTIME_DIR`` (``<tmp>/xut-<uid>/`` without it): ``xut-vivado/`` or ``xut-xsim/``.
It scans the slots without blocking and takes the first free one, and when every slot is
held it waits, scanning again every ``POLL_S``. ``flock`` locks belong to an open file
description, so the limit holds across processes and across threads of one process alike,
and the kernel releases a slot when its holder dies.

The slots are only a semaphore, never a second memory budget: every run happens inside the
scope of the heavy command that started it, whose cap must cover the runs it holds slots
for (AGENTS.md §10.1).
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
XSIM_SLOTS_ENV = "XUT_XSIM_SLOTS"
DEFAULT_XSIM_SLOTS = 12
#: kind -> (environment variable, default count, directory under the runtime dir)
KINDS = {
    "vivado": (SLOTS_ENV, DEFAULT_SLOTS, "xut-vivado"),
    "xsim": (XSIM_SLOTS_ENV, DEFAULT_XSIM_SLOTS, "xut-xsim"),
}
POLL_S = 0.5


def _kind(kind: str) -> tuple[str, int, str]:
    if kind not in KINDS:
        raise XutError(f"unknown slot kind {kind!r} (known: {sorted(KINDS)})")
    return KINDS[kind]


def slot_dir(kind: str = "vivado") -> Path:
    """``$XDG_RUNTIME_DIR/xut-<kind>`` (``<tmp>/xut-<uid>/xut-<kind>`` without it)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or str(
        Path(tempfile.gettempdir()) / f"xut-{os.getuid()}"
    )
    return Path(base) / _kind(kind)[2]


def slot_count(kind: str = "vivado") -> int:
    """``$XUT_VIVADO_SLOTS`` (default 4) or, for ``kind="xsim"``, ``$XUT_XSIM_SLOTS``
    (default 12); ``XutError`` unless it is a positive integer."""
    env, default, _ = _kind(kind)
    raw = os.environ.get(env, str(default))
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n < 1:
        raise XutError(f"${env}={raw!r} is not a positive integer")
    return n


@contextmanager
def vivado_slot(
    n: int | None = None,
    lock_dir: Path | None = None,
    *,
    kind: str = "vivado",
    poll_s: float = POLL_S,
    log: Callable[[str], None] | None = None,
) -> Iterator[int]:
    """Hold one of ``n`` (``slot_count(kind)``) slots in ``lock_dir`` (``slot_dir(kind)``)
    for the body; yields the slot's index. ``log`` is told once when every slot is busy."""
    n = slot_count(kind) if n is None else n
    if n < 1:
        raise XutError(f"vivado_slot: {n} slots")
    d = Path(lock_dir) if lock_dir is not None else slot_dir(kind)
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
