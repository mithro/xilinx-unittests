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
import json
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
#: Backfill (below): at most one command backfills at a time; the head's wait is published
#: in HEAD_FILE; after BACKFILL_AGE_S of waiting no command overtakes it any more.
BACKFILL = "backfill.lock"
HEAD_FILE = "head.json"
BACKFILL_AGE_S = 300.0
POLL_S = 1.0
_NAME = re.compile(r"[A-Za-z0-9_.-]+")
#: The parallelism options of each tool, as ``tool -> regex``; a match's value is group 1
#: (``--opt=N``, ``-nN``) or else the next word. Only a command of that tool counts: ``tail
#: -n 50`` or ``git log -n 3`` is not parallelism (review nit).
_PAR = {
    "pytest": re.compile(r"^(?:-n|--numprocesses)(?:=(.*))?$|^-n(\w+)$"),
    "xut": re.compile(r"^--jobs(?:=(.*))?$"),
    "make": re.compile(r"^(?:-j|--jobs)(?:=(.*))?$|^-j(\w+)$"),
}
_PAR["ninja"] = _PAR["make"]
_SHELLS = {"bash", "sh", "dash", "zsh"}
#: Shell operators that end one command of a ``bash -c`` script.
_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}


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
        size_bytes(mem.lower(), f"--mem {mem}")
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


def _commands(argv: Sequence[str]) -> list[list[str]]:
    """``argv`` and, for each ``bash -c``/``sh -c`` it runs, each command of that script
    (split at ``;``, ``&&``, ``|`` and the like), as word lists."""
    out = [list(argv)]
    for i, a in enumerate(argv[:-2]):
        if Path(a).name in _SHELLS and argv[i + 1] == "-c":
            lex = shlex.shlex(argv[i + 2], posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            lex.commenters = "#"
            try:
                words = list(lex)
            except ValueError:
                words = argv[i + 2].split()
            cmd: list[str] = []
            for w in words:
                if w in _SEPARATORS or set(w) <= set(";&|()"):
                    out.append(cmd)
                    cmd = []
                else:
                    cmd.append(w)
            out.append(cmd)
    return [c for c in out if c]


def _tool(cmd: list[str]) -> tuple[str, int] | None:
    """The tool whose parallelism options ``cmd`` takes (``_PAR``), and where its name is,
    if any: the first word naming it (``pytest``, ``python -m pytest``, ``uv run xut``,
    ``make``). Only the words after it are the tool's options: a wrapper's own flags before
    it (``nice -n 19``, ``ionice -n7``, ``timeout -k 10``) never count."""
    names = [Path(w).name for w in cmd]
    for i, n in enumerate(names):
        if n in _PAR:
            return n, i
    return None


def declared_parallelism(argv: Sequence[str]) -> int | None:
    """The largest parallelism a command declares (None without one): pytest's ``-n``, xut's
    ``--jobs``, make/ninja's ``-j``, each counted only in a command of that tool, in
    ``argv`` or in a ``bash -c`` script it runs. Best effort: a script file is not read.
    ``XutError`` for pytest's ``-n auto``/``logical``: 88 workers on this host (AGENTS.md
    §10.1)."""
    found: list[int] = []
    for cmd in _commands(argv):
        at = _tool(cmd)
        if at is None:
            continue
        tool, start = at
        for i, a in enumerate(cmd):
            if i <= start:
                continue
            m = _PAR[tool].match(a)
            if not m:
                continue
            value = next((g for g in m.groups() if g), None)
            if value is None:
                value = cmd[i + 1] if i + 1 < len(cmd) else ""
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
    backfill_age_s: float = BACKFILL_AGE_S,
) -> Iterator[list[int]]:
    """Hold ``need`` of the ``TOKENS`` tokens in ``d`` (``token_dir()``) and ``legacy``
    (``runtime_dir() / LEGACY_LOCK``) shared for the body; yields the file descriptors that
    hold them (for ``pass_fds``). ``log`` is told once when the command has to wait.

    **Backfill.** The command holding the gate (the head) waits for its tokens; while it
    has waited less than ``backfill_age_s``, a later command waiting for the gate that
    needs no more than the free tokens is admitted ahead of it (``_backfill``). Every token
    is still an exclusive ``flock``, so the budget holds whatever the order. After
    ``backfill_age_s`` no command overtakes the head: it gets the next tokens released, so
    it waits at most that much longer than it would have (no starvation)."""
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
        with (d / GATE).open("a") as gate:
            held = None
            if not _try(gate):
                say("xut heavy: waiting for earlier commands to be admitted")
                while True:  # wait for the gate, backfilling when the budget allows
                    held = _backfill(d, need, stack, backfill_age_s)
                    if held is not None:
                        say(
                            f"xut heavy: admitted with {need} tokens ({need * TOKEN_G}G of "
                            f"{BUDGET_G}G), backfilled ahead of a larger waiting command"
                        )
                        break
                    if _try(gate):
                        break
                    time.sleep(poll_s)
            if held is None:
                held = _take_tokens(d, need, stack, poll_s, say, backfill_age_s)
                # said while the gate is still held, so admissions are reported in the
                # order they happen (the next command cannot be admitted before this line)
                say(f"xut heavy: admitted with {need} tokens ({need * TOKEN_G}G of {BUDGET_G}G)")
            # the gate is released here, once every token is held
        yield [old.fileno(), *(h.fileno() for h in held)]


def _publish_head(d: Path, need: int) -> None:
    """The gate holder waits: say since when and for how many tokens (``_backfill``)."""
    tmp = d / f".{HEAD_FILE}.{os.getpid()}"
    tmp.write_text(json.dumps({"need": need, "since": time.time(), "pid": os.getpid()}))
    tmp.replace(d / HEAD_FILE)


def _clear_head(d: Path) -> None:
    (d / HEAD_FILE).unlink(missing_ok=True)


def _head_age(d: Path) -> float | None:
    """How long the head has waited for its tokens, or None when none waits (no file, or
    its process has died: a killed head frees the gate, and its file must not stop every
    later backfill)."""
    try:
        head = json.loads((d / HEAD_FILE).read_text())
        pid, since = int(head["pid"]), float(head["since"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # alive, another user's (never: the directory is per user)
    return time.time() - since


def _take_all_or_none(
    d: Path, need: int, stack: ExitStack, held: dict[int, IO[str]] | None = None
) -> list[IO[str]] | None:
    """Take ``need`` tokens now, all or none (a partial take is given back), under the
    backfill lock (``BACKFILL``: one such attempt at a time). ``held`` (the head's tokens
    already held, kept) counts towards ``need``."""
    held = dict(held or {})
    with (d / BACKFILL).open("a") as bf:
        fcntl.flock(bf, fcntl.LOCK_EX)
        got: dict[int, IO[str]] = {}
        for i in range(TOKENS):
            if len(held) + len(got) == need:
                break
            if i in held:
                continue
            f = (d / f"token{i:02d}.lock").open("a")
            if _try(f):
                got[i] = f
            else:
                f.close()
        if len(held) + len(got) < need:
            for f in got.values():
                f.close()  # releases the flock
            return None
        for f in got.values():
            stack.callback(f.close)
        return [*held.values(), *got.values()]


def _backfill(d: Path, need: int, stack: ExitStack, max_age_s: float) -> list[IO[str]] | None:
    """Take ``need`` tokens without the gate, if that is allowed and they are free now:
    only while the head has waited less than ``max_age_s`` (a head that has not started
    waiting yet does not block a backfill either); all or nothing."""
    age = _head_age(d)
    if age is not None and age >= max_age_s:
        return None
    return _take_all_or_none(d, need, stack)


def _take_tokens(
    d: Path,
    need: int,
    stack: ExitStack,
    poll_s: float,
    say: Callable[[str], None],
    max_age_s: float = BACKFILL_AGE_S,
) -> list[IO[str]]:
    """Take ``need`` tokens in ``d``, waiting for them as they are released; called only
    while holding the gate (the head). The wait is published (``_publish_head``) and
    cleared once admitted. While it is younger than ``max_age_s`` the head takes its tokens
    all at once or not at all, so free tokens stay free for a backfill (``_backfill``);
    after that it keeps every token it gets until it has ``need``, and no backfill overtakes
    it any more (no starvation). Each held token's file is closed (released) by ``stack``."""
    held: dict[int, IO[str]] = {}
    since = time.monotonic()
    waited = False
    while True:
        if time.monotonic() - since < max_age_s:
            got = _take_all_or_none(d, need, stack)
            if got is not None:
                if waited:
                    _clear_head(d)
                return got
        else:  # past the age cap: hoard (under the backfill lock: no backfill in between)
            with (d / BACKFILL).open("a") as bf:
                fcntl.flock(bf, fcntl.LOCK_EX)
                for i in range(TOKENS):
                    if len(held) == need:
                        break
                    if i in held:
                        continue
                    f = (d / f"token{i:02d}.lock").open("a")
                    if _try(f):
                        held[i] = f
                        stack.callback(f.close)
                    else:
                        f.close()
            if len(held) == need:
                _clear_head(d)
                return list(held.values())
        if not waited:
            _publish_head(d, need)
            say(
                f"xut heavy: waiting for {need} of {TOKENS} tokens "
                f"({need * TOKEN_G}G of {BUDGET_G}G); holding {len(held)}"
            )
            waited = True
        time.sleep(poll_s)


#: The command runs at the lowest CPU and best-effort I/O priority (host rule: heavy work
#: yields to interactive sessions). A prefix INSIDE the scope, because ``systemd-run
#: --scope`` adopts the process it starts and never execs it, so ``-p Nice=`` and the
#: ``IOScheduling*`` properties have no effect on a scope. Never the idle I/O class (it can
#: starve the job entirely).
LOW_PRIORITY = ("nice", "-n", "19", "ionice", "-c2", "-n7")


def scope_argv(name: str, mem: str, command: Sequence[str]) -> list[str]:
    """The capped-scope command line (AGENTS.md §10.1). ``systemd-run --scope`` runs the
    command itself, so the command inherits this process's environment and fds; the command
    line is never environment-expanded by systemd (``--expand-environment=no``), and runs
    under ``LOW_PRIORITY``."""
    if not _NAME.fullmatch(name):
        raise XutError(f"--name {name!r}: use letters, digits, '_', '.' and '-' only")
    return [
        "systemd-run", "--user", "--scope", "--slice=vivado.slice",
        f"--unit=xut-{name}-{int(time.time())}",
        # the command is passed as written: never let systemd expand $VAR in it
        "--expand-environment=no",
        "-p", f"MemoryMax={mem}", "-p", "MemorySwapMax=0", "--", *LOW_PRIORITY, *command,
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
    mem = mem.upper()  # one spelling for the budget and the cap: MemoryMax=8G
    need = tokens_for(mem, containers, vivado=vivado)
    argv = scope_argv(name, mem, command)
    env = {**os.environ, NESTED_ENV: "1", VIVADO_ENV: str(vivado)}
    with admit(need, log=log) as fds:
        if execute is not None:
            return execute(argv, fds, env)
        return subprocess.run(argv, pass_fds=fds, env=env).returncode
