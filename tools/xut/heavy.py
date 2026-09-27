# SPDX-License-Identifier: Apache-2.0
"""``xut heavy``: admit a heavy command by memory budget, then run it in a capped scope
(AGENTS.md §10.1).

This replaces the single host mutex (``flock "$XDG_RUNTIME_DIR/xut-heavy.lock"``), which ran
one heavy command at a time however little memory it declared, with a counting semaphore
over the project's budget:

- The budget is ``BUDGET_G`` (96G) in ``TOKENS`` (24) tokens of ``TOKEN_G`` (4G). A token is
  an exclusive ``flock`` on ``token<i>.lock`` in ``$XDG_RUNTIME_DIR/xut-heavy.d/``.
- A command declares its scope cap (``--mem``) and the most containers it runs at once
  (``--containers``; each is capped at ``$XUT_CONTAINER_MEMORY``, 4g by default). It needs
  ``ceil((mem + containers x container cap) / 4G)`` tokens, the same budget as before
  (scope cap + jobs x container cap), and it runs only while it holds them all. So the
  sum of the caps of every admitted command stays at most 96G, which is the invariant the
  single mutex kept for its one command.
- **Fairness.** Tokens are taken only under ``gate.lock``. The command at the head of the
  queue holds the gate until it has all its tokens, so a large command is never starved by
  a stream of small ones, and no two commands can each hold part of what the other needs
  (no deadlock).
- **Lifetime.** The token locks are passed to the command (``pass_fds``), as ``flock(1)``
  passes its lock, so they are held for as long as the command runs, even if this process
  dies first. The kernel releases them when the last holder exits.
- **The old mutex.** Every admitted command also holds ``xut-heavy.lock`` *shared*. A
  command still started with the old ``flock "$XDG_RUNTIME_DIR/xut-heavy.lock" ...`` takes
  it exclusively, so it waits until no admitted command runs and then runs alone, with the
  whole budget. Old and new callers can therefore share the host during the change-over.
- The Vivado slots (``xut.slots``, 4 host-wide) are unchanged. xsim and Vivado run inside
  the scope of the command that starts them, so the command's ``--mem`` must cover them.

The command runs as ``systemd-run --user --scope --slice=vivado.slice
--unit=xut-<name>-<epoch> -p MemoryMax=<mem> -p MemorySwapMax=0 -- <command>``. Its exit
code is returned.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import IO

from xut.container import container_memory, size_bytes
from xut.errors import XutError

BUDGET_G = 96
TOKEN_G = 4
TOKENS = BUDGET_G // TOKEN_G
_G = 1 << 30
#: The single host mutex this replaces; admitted commands hold it shared.
LEGACY_LOCK = "xut-heavy.lock"
GATE = "gate.lock"
POLL_S = 1.0
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
#: A parallelism option in the command: xut's ``--jobs N`` or pytest-xdist's ``-n N``.
_PAR = re.compile(r"^(?:--jobs|-n|--numprocesses)(?:=(.*))?$|^-n(\d+)$")


def runtime_dir() -> Path:
    """``$XDG_RUNTIME_DIR`` (``<tmp>/xut-<uid>`` without it), as ``xut.slots`` uses."""
    base = os.environ.get("XDG_RUNTIME_DIR") or str(
        Path(tempfile.gettempdir()) / f"xut-{os.getuid()}"
    )
    return Path(base)


def token_dir() -> Path:
    return runtime_dir() / "xut-heavy.d"


def tokens_for(mem: str, containers: int, container_cap: str | None = None) -> int:
    """The tokens a command needs: its scope cap ``mem`` plus ``containers`` containers at
    the container cap, rounded up to whole ``TOKEN_G`` tokens. ``XutError`` when that is
    more than the whole budget: such a command can never be admitted."""
    cap = container_memory(container_cap)
    total = size_bytes(mem.lower(), "--mem") + containers * size_bytes(cap, "container cap")
    need = -(-total // (TOKEN_G * _G))
    if need > TOKENS:
        raise XutError(
            f"--mem {mem} + {containers} containers x {cap} = {total / _G:.1f}G is over the "
            f"{BUDGET_G}G budget (AGENTS.md §10.1): lower --mem or the parallelism"
        )
    return need


def declared_parallelism(argv: Sequence[str]) -> int | None:
    """The largest ``--jobs N`` / ``-n N`` in ``argv`` (None without one). ``XutError`` for
    ``-n auto``/``logical``: 88 workers on this host (AGENTS.md §10.1)."""
    found: list[int] = []
    for i, a in enumerate(argv):
        m = _PAR.match(a)
        if not m:
            continue
        value = m.group(2) or m.group(1) or (argv[i + 1] if i + 1 < len(argv) else "")
        if value in ("auto", "logical"):
            raise XutError(f"{a} {value}: give an explicit number (AGENTS.md §10.1)")
        if value.isdigit():
            found.append(int(value))
    return max(found) if found else None


def _try(f: IO[str]) -> bool:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


@contextmanager
def admit(
    need: int,
    d: Path | None = None,
    legacy: Path | None = None,
    *,
    poll_s: float = POLL_S,
    log: Callable[[str], None] | None = None,
) -> Iterator[list[int]]:
    """Hold ``need`` of the ``TOKENS`` tokens in ``d`` (``token_dir()``) and ``legacy``
    (``runtime_dir() / LEGACY_LOCK``) shared for the body; yields the file descriptors that
    hold them (for ``pass_fds``). ``log`` is told once when the command has to wait."""
    if not 1 <= need <= TOKENS:
        raise XutError(f"xut heavy: {need} tokens (1..{TOKENS})")
    d = token_dir() if d is None else Path(d)
    d.mkdir(parents=True, exist_ok=True)
    legacy = runtime_dir() / LEGACY_LOCK if legacy is None else Path(legacy)
    say = log or (lambda _s: None)
    with ExitStack() as stack:
        old = stack.enter_context(legacy.open("a"))
        try:
            fcntl.flock(old, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            say(f"xut heavy: waiting for a command holding {legacy} alone (the old mutex)")
            fcntl.flock(old, fcntl.LOCK_SH)
        held: list[IO[str]] = []
        with (d / GATE).open("a") as gate:
            if not _try(gate):
                say("xut heavy: waiting for earlier commands to be admitted")
                fcntl.flock(gate, fcntl.LOCK_EX)
            waited = False
            while True:
                for i in range(TOKENS):
                    if len(held) == need:
                        break
                    p = d / f"token{i:02d}.lock"
                    if any(h.name == str(p) for h in held):
                        continue
                    f = p.open("a")
                    if _try(f):
                        held.append(f)
                        stack.callback(f.close)
                    else:
                        f.close()
                if len(held) == need:
                    break
                if not waited:
                    say(
                        f"xut heavy: waiting for {need} of {TOKENS} tokens "
                        f"({need * TOKEN_G}G of {BUDGET_G}G); holding {len(held)}"
                    )
                    waited = True
                time.sleep(poll_s)
            # the gate is released here, once every token is held
        say(f"xut heavy: admitted with {need} tokens ({need * TOKEN_G}G of {BUDGET_G}G)")
        yield [old.fileno(), *(h.fileno() for h in held)]


def scope_argv(name: str, mem: str, command: Sequence[str]) -> list[str]:
    """The capped-scope command line (AGENTS.md §10.1)."""
    if not _NAME.fullmatch(name):
        raise XutError(f"--name {name!r}: use letters, digits, '_', '.' and '-' only")
    return [
        "systemd-run", "--user", "--scope", "--slice=vivado.slice",
        f"--unit=xut-{name}-{int(time.time())}",
        "-p", f"MemoryMax={mem.upper()}", "-p", "MemorySwapMax=0", "--", *command,
    ]  # fmt: skip


def run(
    mem: str,
    containers: int,
    name: str,
    command: Sequence[str],
    *,
    log: Callable[[str], None] | None = None,
    execute: Callable[[list[str], list[int]], int] | None = None,
) -> int:
    """Check the declaration, wait for admission, run ``command`` in its scope; its exit
    code. ``execute`` (tests) replaces running the scope."""
    if not command:
        raise XutError("xut heavy: no command given (put it after --)")
    par = declared_parallelism(command)
    if par is not None and par > containers:
        raise XutError(
            f"the command runs {par} jobs but --containers is {containers}: declare at least "
            f"{par} (each job may hold one container; AGENTS.md §10.1)"
        )
    need = tokens_for(mem, containers)
    argv = scope_argv(name, mem, command)
    with admit(need, log=log) as fds:
        if execute is not None:
            return execute(argv, fds)
        return subprocess.run(argv, pass_fds=fds).returncode
