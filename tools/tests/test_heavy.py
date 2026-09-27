# SPDX-License-Identifier: Apache-2.0
"""xut.heavy: memory-budget admission of heavy commands (AGENTS.md §10.1), on private
lock directories."""

import fcntl
import subprocess
import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from xut import heavy
from xut.cli import main
from xut.errors import XutError


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
    ],
)
def test_declared_parallelism(argv, n):
    assert heavy.declared_parallelism(argv) == n


@pytest.mark.parametrize("argv", [["pytest", "-n", "auto"], ["pytest", "-n", "logical"]])
def test_automatic_worker_counts_are_refused(argv):
    with pytest.raises(XutError, match="explicit number"):
        heavy.declared_parallelism(argv)


def test_fewer_containers_than_jobs_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    with pytest.raises(XutError, match="runs 16 jobs but --containers is 4"):
        heavy.run("8G", 4, "x", ["xut", "run", "--jobs", "16"], execute=lambda a, f: 0)


def test_scope_argv():
    argv = heavy.scope_argv("flops-run", "8g", ["uv", "run", "xut", "run"])
    assert argv[:4] == ["systemd-run", "--user", "--scope", "--slice=vivado.slice"]
    assert argv[4].startswith("--unit=xut-flops-run-")
    assert argv[5:] == [
        "-p", "MemoryMax=8G", "-p", "MemorySwapMax=0", "--", "uv", "run", "xut", "run",
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


def _admit_in_thread(need, d, legacy, events, key, release):
    def body():
        with heavy.admit(need, d, legacy, poll_s=0.01):
            events.append(f"{key} in")
            release.wait(5)
        events.append(f"{key} out")

    t = threading.Thread(target=body)
    t.start()
    return t


def test_a_command_over_the_free_budget_waits(tmp_path):
    d, legacy = _dirs(tmp_path)
    events: list[str] = []
    go = threading.Event()
    go.set()
    with heavy.admit(20, d, legacy):
        t = _admit_in_thread(8, d, legacy, events, "b", go)
        time.sleep(0.2)
        assert events == []  # 20 + 8 > 24: waits
    t.join(5)
    assert events == ["b in", "b out"]


def test_the_head_of_the_queue_is_never_overtaken(tmp_path):
    """A small command that would fit waits behind a larger one that came first."""
    d, legacy = _dirs(tmp_path)
    events: list[str] = []
    rel = threading.Event()
    with heavy.admit(20, d, legacy):
        b = _admit_in_thread(8, d, legacy, events, "b", rel)
        time.sleep(0.2)
        c = _admit_in_thread(2, d, legacy, events, "c", rel)  # 2 of the 4 free would fit
        time.sleep(0.2)
        assert events == []
    time.sleep(0.3)
    assert events[0] == "b in" and "c in" in events  # b first, then c beside it (8 + 2)
    rel.set()
    b.join(5)
    c.join(5)


def test_the_old_mutex_and_admitted_commands_exclude_each_other(tmp_path):
    d, legacy = _dirs(tmp_path)
    with heavy.admit(1, d, legacy):
        assert _held(legacy)  # an old-style flock (exclusive) waits
    events: list[str] = []
    go = threading.Event()
    go.set()
    with legacy.open("a") as old:
        fcntl.flock(old, fcntl.LOCK_EX)  # an old-style command runs alone
        t = _admit_in_thread(1, d, legacy, events, "new", go)
        time.sleep(0.2)
        assert events == []
        fcntl.flock(old, fcntl.LOCK_UN)
    t.join(5)
    assert events == ["new in", "new out"]


def test_the_locks_are_passed_to_the_command(tmp_path, monkeypatch):
    """The command inherits the token locks (pass_fds), so they are held while it runs,
    as flock(1) passes its lock to its command."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    d = heavy.token_dir()
    probe = (
        "import fcntl, os, sys\n"
        "fds = [int(x) for x in sys.argv[1:]]\n"
        "print(all(os.fstat(f) is not None for f in fds))\n"
    )

    def execute(argv, fds):
        assert argv[0] == "systemd-run" and argv[-2:] == ["run", "--jobs=2"]
        cmd = ["python3", "-c", probe, *map(str, fds)]
        out = subprocess.run(cmd, pass_fds=fds, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == "True"
        assert sum(_held(t) for t in d.glob("token*.lock")) == 3  # 4G + 2 x 4g
        return 7

    assert heavy.run("4G", 2, "t", ["xut", "run", "--jobs=2"], execute=execute) == 7


def test_cli_exits_with_the_commands_code(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    seen = {}

    def fake_run(argv, pass_fds):
        seen["argv"], seen["fds"] = argv, pass_fds
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(heavy.subprocess, "run", fake_run)
    res = CliRunner().invoke(
        main, ["heavy", "--mem", "8G", "--containers", "2", "--name", "t", "--", "pytest", "-n2"]
    )
    assert res.exit_code == 3, res.output
    assert seen["argv"][-2:] == ["pytest", "-n2"] and len(seen["fds"]) == 5
    assert "admitted with 4 tokens" in res.output


def test_cli_refuses_a_command_over_the_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    res = CliRunner().invoke(main, ["heavy", "--mem", "96G", "--containers", "1", "--", "true"])
    assert res.exit_code == 1 and "over the 96G budget" in res.output
