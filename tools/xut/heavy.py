# SPDX-License-Identifier: Apache-2.0
"""``xut heavy``: admit a heavy command by memory budget, then run it in a capped scope
(AGENTS.md §10.1).

This replaces the single host mutex (``flock "$XDG_RUNTIME_DIR/xut-heavy.lock"``), which ran
one heavy command at a time however little memory it declared, with a counting semaphore
over the project's budget:

- The budget is ``BUDGET_G`` (96G) in ``TOKENS`` (24) tokens of ``TOKEN_G`` (4G). A token is
  an exclusive ``flock`` on ``token<i>.lock`` in ``$XDG_RUNTIME_DIR/xut-heavy.d/``.
- A command declares everything that runs on its behalf:
  - its scope cap (``--mem``);
  - the most containers it runs at once (``--containers``; each is capped at
    ``$XUT_CONTAINER_MEMORY``, 4g by default);
  - the most Vivado or xsim runs it starts **in their own scopes** at once
    (``--vivado``; each is a 16G scope, ``VIVADO_G``; step 3's ``scoped_run``).

  It needs ``ceil((mem + containers x container cap + vivado x 16G) / 4G)`` tokens and runs
  only while it holds them all, so the sum of the caps of every admitted command and of
  everything it starts stays at most 96G: the invariant the single mutex kept for its one
  command. The scope gets ``XUT_HEAVY_VIVADO=<vivado>`` in its environment, so code that
  starts its own 16G scopes can refuse to (fail closed) when the caller reserved none
  (``vivado_reserved``). ``--containers`` and ``--vivado`` are the caller's declarations:
  ``declared_parallelism`` checks the command line (and a ``bash -c``/``sh -c`` script) for
  a larger ``--jobs``/``-j``/``-n``, best-effort; it cannot see into scripts.
- **Order.** Tokens are taken only under ``gate.lock``. A command holding the gate keeps it
  until it has all its tokens, so it is never overtaken by later, smaller commands, and no
  two commands can each hold part of what the other needs (no deadlock). Commands still
  waiting for the gate itself are not woken in FIFO order (``flock`` makes no such
  promise), so a large command can lose the gate to later ones a few times; it is never
  overtaken once it holds the gate.
- **No nesting.** The scope gets ``XUT_HEAVY=1``: ``xut heavy`` inside it is refused, since
  it would wait for tokens its parent holds (a deadlock).
- **Containers.** Docker containers are children of ``dockerd``, not of the command, so
  they do not inherit the tokens: if the command is killed, its containers may run on
  (each at its cap) after the tokens are released, until ``xut container`` sweeps them or
  they end. The single mutex had the same gap.
- **Lifetime.** The token locks are passed to the command (``pass_fds``), as ``flock(1)``
  passes its lock, so they are held for as long as the command runs, even if this process
  dies first. The kernel releases them when the last holder exits.
- **The old mutex.** Every admitted command also holds ``xut-heavy.lock`` *shared*. A
  command still started with the old ``flock "$XDG_RUNTIME_DIR/xut-heavy.lock" ...`` takes
  it exclusively, so it waits until no admitted command runs and then runs alone, with the
  whole budget. Old and new callers can therefore share the host during the change-over,
  but ``flock`` grants new shared locks while an exclusive one waits, so an old-style
  command may wait a long time while ``xut heavy`` commands keep arriving: switch to
  ``xut heavy``.
- ``$XDG_RUNTIME_DIR`` must be set: it is the one directory every session of this user
  shares (and ``systemd-run --user`` needs it); there is no fallback.
- The Vivado slots (``xut.slots``) are unchanged. A run inside the caller's own scope is
  covered by ``--mem``; a run in a scope of its own by ``--vivado``.

The command runs as ``systemd-run --user --scope --slice=vivado.slice
--unit=xut-<name>-<epoch> -p MemoryMax=<mem> -p MemorySwapMax=0 -- <command>``. Its exit
code is returned.
"""

from __future__ import annotations

import fcntl
import os
import re
import shlex
import subprocess
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
#: The size of one Vivado/xsim run in a scope of its own (``--vivado``; AGENTS.md §10.1).
VIVADO_G = 16
#: Set in the scope: nesting refused; the ``--vivado`` reservation for ``scoped_run``.
NESTED_ENV = "XUT_HEAVY"
VIVADO_ENV = "XUT_HEAVY_VIVADO"
_G = 1 << 30
#: The single host mutex this replaces; admitted commands hold it shared.
LEGACY_LOCK = "xut-heavy.lock"
GATE = "gate.lock"
POLL_S = 1.0
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
#: A parallelism option: xut's ``--jobs N``, make/ninja-style ``-j N`` or pytest-xdist's
#: ``-n N`` (also ``--opt=N`` and ``-nN``/``-jN``).
_PAR = re.compile(r"^(?:--jobs|-j|-n|--numprocesses)(?:=(.*))?$|^-[nj](\w+)$")
_SHELLS = {"bash", "sh", "dash", "zsh"}


def runtime_dir() -> Path:
    """``$XDG_RUNTIME_DIR``: ``XutError`` when it is unset, never another directory (every
    session must use the same locks)."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        raise XutError(
            "$XDG_RUNTIME_DIR is not set: xut heavy's locks live there, shared by every "
            "session of this user, and systemd-run --user needs it (AGENTS.md §10.1)"
        )
    return Path(base)


def vivado_reserved() -> int:
    """The ``--vivado`` reservation of the ``xut heavy`` command this process runs under.
    ``XutError`` (fail closed) when it runs under none or reserved 0: a 16G scope of its own
    would then be outside the budget."""
    raw = os.environ.get(VIVADO_ENV, "")
    n = int(raw) if raw.isdigit() else 0
    if os.environ.get(NESTED_ENV) != "1" or n < 1:
        raise XutError(
            "starting Vivado/xsim in a 16G scope of its own needs an xut heavy reservation: "
            "run the command as `uv run xut heavy --vivado N ...` (AGENTS.md §10.1)"
        )
    return n


def token_dir() -> Path:
    return runtime_dir() / "xut-heavy.d"


def tokens_for(mem: str, containers: int, container_cap: str | None = None, vivado: int = 0) -> int:
    """The tokens a command needs: its scope cap ``mem`` plus ``containers`` containers at
    the container cap plus ``vivado`` 16G scopes, rounded up to whole ``TOKEN_G`` tokens.
    ``XutError`` when that is more than the whole budget: it could never be admitted."""
    cap = container_memory(container_cap)
    total = (
        size_bytes(mem.lower(), "--mem")
        + containers * size_bytes(cap, "container cap")
        + vivado * VIVADO_G * _G
    )
    need = -(-total // (TOKEN_G * _G))
    if need > TOKENS:
        raise XutError(
            f"--mem {mem} + {containers} containers x {cap} + {vivado} Vivado x {VIVADO_G}G "
            f"= {total / _G:.1f}G is over the {BUDGET_G}G budget (AGENTS.md §10.1): lower "
            "--mem or the parallelism"
        )
    return need


def _words(argv: Sequence[str]) -> list[str]:
    """``argv``, with the script of each ``bash -c``/``sh -c`` split into words too."""
    out = list(argv)
    for i, a in enumerate(argv[:-1]):
        if Path(a).name in _SHELLS and argv[i + 1] == "-c" and i + 2 < len(argv):
            try:
                out += shlex.split(argv[i + 2], comments=True)
            except ValueError:
                out += argv[i + 2].split()
    return out


def declared_parallelism(argv: Sequence[str]) -> int | None:
    """The largest ``--jobs``/``-j``/``-n`` value in ``argv`` or in a ``bash -c`` script it
    runs (None without one); best-effort: a script file is not read. ``XutError`` for ``-n
    auto``/``logical``: 88 workers on this host (AGENTS.md §10.1)."""
    argv = _words(argv)
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
    """The capped-scope command line (AGENTS.md §10.1). ``systemd-run --scope`` runs the
    command itself, so the command inherits this process's environment and fds; the command
    line is never environment-expanded by systemd (``--expand-environment=no``)."""
    if not _NAME.fullmatch(name):
        raise XutError(f"--name {name!r}: use letters, digits, '_', '.' and '-' only")
    return [
        "systemd-run", "--user", "--scope", "--slice=vivado.slice",
        f"--unit=xut-{name}-{int(time.time())}",
        # the command is passed as written: never let systemd expand $VAR in it
        "--expand-environment=no",
        "-p", f"MemoryMax={mem.upper()}", "-p", "MemorySwapMax=0", "--", *command,
    ]  # fmt: skip


def run(
    mem: str,
    containers: int,
    name: str,
    command: Sequence[str],
    *,
    vivado: int = 0,
    log: Callable[[str], None] | None = None,
    execute: Callable[[list[str], list[int], dict[str, str]], int] | None = None,
) -> int:
    """Check the declaration, wait for admission, run ``command`` in its scope; its exit
    code. ``execute`` (tests) replaces running the scope."""
    if os.environ.get(NESTED_ENV) == "1":
        raise XutError(
            "xut heavy inside xut heavy is refused: the inner command would wait for tokens "
            "the outer one holds (a deadlock); declare everything on the outer command"
        )
    if not command:
        raise XutError("xut heavy: no command given (put it after --)")
    if vivado < 0:
        raise XutError(f"--vivado {vivado}: must be 0 or more")
    par = declared_parallelism(command)
    if par is not None and par > containers:
        raise XutError(
            f"the command runs {par} jobs but --containers is {containers}: declare at least "
            f"{par} (each job may hold one container; AGENTS.md §10.1)"
        )
    need = tokens_for(mem, containers, vivado=vivado)
    argv = scope_argv(name, mem, command)
    env = {**os.environ, NESTED_ENV: "1", VIVADO_ENV: str(vivado)}
    with admit(need, log=log) as fds:
        if execute is not None:
            return execute(argv, fds, env)
        return subprocess.run(argv, pass_fds=fds, env=env).returncode
