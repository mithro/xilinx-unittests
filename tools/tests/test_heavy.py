# SPDX-License-Identifier: Apache-2.0
"""xut.heavy: memory-budget admission of heavy commands (AGENTS.md §10.1), on private
lock directories."""

import fcntl
import subprocess
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from xut import heavy
from xut.cli import main
from xut.errors import XutError


@pytest.fixture(autouse=True)
def _not_nested(monkeypatch):
    """The suite itself may run under xut heavy (which sets these): not the tests."""
    monkeypatch.delenv(heavy.NESTED_ENV, raising=False)
    monkeypatch.delenv(heavy.VIVADO_ENV, raising=False)


@pytest.mark.parametrize(
    ("mem", "containers", "need"),
    [("32G", 16, 24), ("8G", 0, 2), ("8g", 2, 4), ("3G", 0, 1), ("16G", 4, 8), ("512m", 1, 2)],
)
def test_tokens_for(mem, containers, need, monkeypatch):
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    assert heavy.tokens_for(mem, containers) == need


def test_tokens_for_uses_the_container_cap(monkeypatch):
    monkeypatch.setenv("XUT_CONTAINER_MEMORY", "8g")
    assert heavy.tokens_for("8G", 2) == 6


def test_vivado_scopes_count_16g_each(monkeypatch):
    """Review must-fix: Vivado/xsim runs in scopes of their own are in the budget."""
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    assert heavy.tokens_for("4G", 0, vivado=4) == 17  # 4G + 64G
    assert heavy.tokens_for("8G", 4, vivado=4) == 22  # 8 + 16 + 64 = 88G
    with pytest.raises(XutError, match="4 Vivado x 16G .* over the 96G budget"):
        heavy.tokens_for("20G", 4, vivado=4)  # 20 + 16 + 64 = 100G


def test_vivado_reserved_fails_closed(monkeypatch):
    with pytest.raises(XutError, match="needs an xut heavy reservation"):
        heavy.vivado_reserved()  # not under xut heavy
    monkeypatch.setenv(heavy.NESTED_ENV, "1")
    monkeypatch.setenv(heavy.VIVADO_ENV, "0")
    with pytest.raises(XutError, match="--vivado N"):
        heavy.vivado_reserved()  # under xut heavy, nothing reserved
    monkeypatch.setenv(heavy.VIVADO_ENV, "2")
    assert heavy.vivado_reserved() == 2
    monkeypatch.delenv(heavy.NESTED_ENV)
    with pytest.raises(XutError):
        heavy.vivado_reserved()  # the variable alone, outside xut heavy, is not enough


@pytest.mark.parametrize(("mem", "containers"), [("97G", 0), ("32G", 17), ("64G", 9)])
def test_over_the_budget_is_refused(mem, containers, monkeypatch):
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    with pytest.raises(XutError, match="over the 96G budget"):
        heavy.tokens_for(mem, containers)


@pytest.mark.parametrize(
    ("argv", "n"),
    [
        (["uv", "run", "xut", "run", "unit:flops", "--jobs", "16"], 16),
        (["uv", "run", "xut", "run", "--jobs=4"], 4),
        (["uv", "run", "pytest", "-q", "-n", "8"], 8),
        (["uv", "run", "pytest", "-n2", "tools/tests/test_xtr.py"], 2),
        (["uv", "run", "pytest", "--numprocesses=3"], 3),
        (["uv", "run", "xut", "lint"], None),
        (["make", "-j", "6"], 6),
        (["make", "-j12"], 12),
        (["bash", "-c", "cd x && uv run xut run unit:flops --jobs 16 > log 2>&1"], 16),
        (["/bin/sh", "-c", "uv run pytest -n4 -q"], 4),
        (["bash", "script.sh"], None),  # best-effort: a script file is not read
        # another tool's -n/-j is not parallelism (review nit)
        (["bash", "-c", "uv run xut run X --jobs 4 > log 2>&1; tail -n 50 log"], 4),
        (["bash", "-c", "git log -n 30 && head -n 99 f | sort -n"], None),
        (["bash", "-c", "uv run pytest -n 2 x.py|tail -n 40"], 2),
        (["python", "-m", "pytest", "-n", "3"], 3),
        (["ninja", "-j8"], 8),
        (["tail", "-n", "50", "log"], None),
        # a wrapper's own flags are not the tool's (nice -n 19 is a niceness, not jobs)
        (["nice", "-n", "19", "uv", "run", "pytest", "-n", "8"], 8),
        (["ionice", "-c2", "-n7", "uv", "run", "pytest", "-n", "8"], 8),
        # a wrapper's argument naming a tool never hides the real command's options
        (["uv", "run", "--with", "pytest", "xut", "run", "X", "--jobs", "12"], 12),
        (["uv", "run", "--with", "xut", "pytest", "-n", "8"], 8),
        (["ionice", "-c2", "-n", "7", "uv", "run", "xut", "lint"], None),
        (["bash", "-c", "ionice -c2 -n7 uv run pytest -n 3 x.py"], 3),
        (["nice", "--adjustment=19", "ionice", "-c2", "-n7", "uv", "run", "pytest", "-n2"], 2),
        (["nice", "-n", "19", "ionice", "-c2", "-n7", "uv", "run", "xut", "lint"], None),
        (["bash", "-c", "nice -n 19 uv run xut run X --jobs 12 > log 2>&1"], 12),
    ],
)
def test_declared_parallelism(argv, n):
    assert heavy.declared_parallelism(argv) == n


@pytest.mark.parametrize(
    "argv",
    [
        ["pytest", "-n", "auto"],
        ["pytest", "-n", "logical"],
        ["pytest", "-nauto"],
        ["bash", "-c", "uv run pytest -n auto"],
    ],
)
def test_automatic_worker_counts_are_refused(argv):
    with pytest.raises(XutError, match="explicit number"):
        heavy.declared_parallelism(argv)


def test_fewer_containers_than_jobs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with pytest.raises(XutError, match="runs 16 jobs but --containers is 4"):
        heavy.run("8G", 4, "x", ["xut", "run", "--jobs", "16"], execute=lambda a, f, e: 0)
    with pytest.raises(XutError, match="runs 16 jobs"):
        heavy.run("8G", 4, "x", ["bash", "-c", "xut run --jobs 16"], execute=lambda a, f, e: 0)


def test_nesting_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv(heavy.NESTED_ENV, "1")
    with pytest.raises(XutError, match="inside xut heavy is refused"):
        heavy.run("4G", 0, "x", ["true"], execute=lambda a, f, e: 0)


def test_no_runtime_dir_is_an_error(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(XutError, match="XDG_RUNTIME_DIR is not set"):
        heavy.token_dir()


def test_scope_argv():
    argv = heavy.scope_argv("flops-run", "8g", ["uv", "run", "xut", "run"])
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--slice=vivado.slice"]
    assert argv[4].startswith("--unit=xut-flops-run-")
    assert argv[5:] == [
        "--expand-environment=no", "-p", "MemoryMax=8g", "-p", "MemorySwapMax=0",
        "--", "nice", "-n", "19", "ionice", "-c2", "-n7", "uv", "run", "xut", "run",
    ]  # fmt: skip
    with pytest.raises(XutError, match="--name"):
        heavy.scope_argv("a b", "8G", ["true"])


def _held(p: Path) -> bool:
    """``p`` is locked by someone else (an exclusive try fails)."""
    with p.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "xut-heavy.d", tmp_path / "xut-heavy.lock"


def test_commands_within_the_budget_run_together(tmp_path):
    d, legacy = _dirs(tmp_path)
    with heavy.admit(16, d, legacy) as a, heavy.admit(8, d, legacy) as b:
        assert len(a) == 17 and len(b) == 9  # the legacy lock and the tokens
        tokens = sorted(d.glob("token*.lock"))
        assert len(tokens) == heavy.TOKENS and all(_held(t) for t in tokens)
    assert not any(_held(t) for t in d.glob("token*.lock"))  # released on exit


class _Admission:
    """An ``admit`` in a thread, observed through its ``log`` messages (no sleeps)."""

    def __init__(self, need, d, legacy, order):
        self.need, self.order = need, order
        self.waiting_gate, self.waiting_tokens = threading.Event(), threading.Event()
        self.waiting_old, self.admitted = threading.Event(), threading.Event()
        self.release, self.out = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._body, args=(d, legacy))
        self.thread.start()

    def _log(self, line: str) -> None:
        if "earlier commands" in line:
            self.waiting_gate.set()
        elif "waiting for" in line and "tokens" in line:
            self.waiting_tokens.set()
        elif "the old mutex" in line:
            self.waiting_old.set()
        elif "admitted" in line:
            self.order.append(self.need)
            self.admitted.set()

    def _body(self, d, legacy):
        with heavy.admit(self.need, d, legacy, poll_s=0.01, log=self._log):
            self.release.wait(10)
        self.out.set()

    def finish(self):
        self.release.set()
        self.thread.join(10)
        assert not self.thread.is_alive()


def test_a_command_over_the_free_budget_waits(tmp_path):
    d, legacy = _dirs(tmp_path)
    order: list[int] = []
    with heavy.admit(20, d, legacy):
        b = _Admission(8, d, legacy, order)
        assert b.waiting_tokens.wait(10)  # it holds the gate and waits: 20 + 8 > 24
        assert not b.admitted.is_set()
    assert b.admitted.wait(10)  # admitted once the 20 are released
    b.finish()
    assert order == [8]


def test_the_head_of_the_queue_is_never_overtaken(tmp_path):
    """A small command that would fit waits behind a larger one that holds the gate."""
    d, legacy = _dirs(tmp_path)
    order: list[int] = []
    with heavy.admit(20, d, legacy):
        b = _Admission(8, d, legacy, order)
        assert b.waiting_tokens.wait(10)  # b holds the gate
        c = _Admission(2, d, legacy, order)  # 2 of the 4 free would fit
        assert c.waiting_gate.wait(10)  # but c waits for the gate
        assert not b.admitted.is_set() and not c.admitted.is_set()
    assert b.admitted.wait(10) and c.admitted.wait(10)
    assert order == [8, 2]  # b first, then c beside it (8 + 2 of 24)
    b.finish()
    c.finish()


def test_the_old_mutex_and_admitted_commands_exclude_each_other(tmp_path):
    d, legacy = _dirs(tmp_path)
    with heavy.admit(1, d, legacy):
        assert _held(legacy)  # an old-style flock (exclusive) waits
    order: list[int] = []
    with legacy.open("a") as old:
        fcntl.flock(old, fcntl.LOCK_EX)  # an old-style command runs alone
        new = _Admission(1, d, legacy, order)
        assert new.waiting_old.wait(10)
        assert not new.admitted.is_set()
        fcntl.flock(old, fcntl.LOCK_UN)
    assert new.admitted.wait(10)
    new.finish()


def test_the_locks_are_passed_to_the_command(tmp_path, monkeypatch):
    """The command inherits the token locks (pass_fds), so they are held while it runs,
    as flock(1) passes its lock to its command."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    d = heavy.token_dir()
    # The child can take each lock exclusively without blocking only because it holds the
    # very same lock (the inherited open file description): another holder would block it.
    probe = (
        "import fcntl, sys\n"
        "for f in map(int, sys.argv[1:]):\n"
        "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "print('held')\n"
    )

    def execute(argv, fds, env):
        assert argv[0] == "systemd-run" and argv[-2:] == ["run", "--jobs=2"]
        assert env[heavy.NESTED_ENV] == "1" and env[heavy.VIVADO_ENV] == "1"
        cmd = ["python3", "-c", probe, *map(str, fds[1:])]  # the tokens (fds[0]: legacy, shared)
        out = subprocess.run(cmd, pass_fds=fds, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == "held"
        assert sum(_held(t) for t in d.glob("token*.lock")) == 7  # 4G + 2 x 4g + 16G
        return 7

    got = heavy.run("4G", 2, "t", ["xut", "run", "--jobs=2"], vivado=1, execute=execute)
    assert got == 7


def test_cli_exits_with_the_commands_code(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    seen = {}

    def fake_run(argv, pass_fds, env):
        seen["argv"], seen["fds"], seen["env"] = argv, pass_fds, env
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(heavy.subprocess, "run", fake_run)
    res = CliRunner().invoke(
        main, ["heavy", "--mem", "8G", "--containers", "2", "--name", "t", "--", "pytest", "-n2"]
    )
    assert res.exit_code == 3, res.output
    assert seen["argv"][-2:] == ["pytest", "-n2"] and len(seen["fds"]) == 5
    assert "admitted with 4 tokens" in res.output
    assert seen["env"][heavy.VIVADO_ENV] == "0"


def test_cli_refuses_a_command_over_the_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    res = CliRunner().invoke(main, ["heavy", "--mem", "96G", "--containers", "1", "--", "true"])
    assert res.exit_code == 1 and "over the 96G budget" in res.output
