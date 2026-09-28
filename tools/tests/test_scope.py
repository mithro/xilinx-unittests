# SPDX-License-Identifier: Apache-2.0
import shutil
import subprocess

import pytest

from xut import scope
from xut.scope import ScopeError, scope_argv


def test_scope_argv_is_the_agents_md_line():
    argv = scope_argv(["vivado", "-version"], "vivado-x", "16G")
    assert argv[:5] == ["systemd-run", "--user", "--scope", "--quiet", "--slice=vivado.slice"]
    assert argv[5].startswith("--unit=xut-vivado-x-")
    assert argv[6:11] == ["-p", "MemoryMax=16G", "-p", "MemorySwapMax=0", "--"]
    assert argv[11:] == ["vivado", "-version"]


def test_scoped_run_refuses_without_systemd_run(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ScopeError, match="systemd-run"):
        scope.scoped_run(
            ["true"], what="t", memory_max="1G", cwd=tmp_path, log=tmp_path / "l", timeout_s=5
        )


def _user_scopes_work() -> bool:
    if shutil.which("systemd-run") is None:
        return False
    r = subprocess.run(
        ["systemd-run", "--user", "--scope", "--quiet", "--", "true"], capture_output=True
    )
    return r.returncode == 0


@pytest.mark.skipif(
    not _user_scopes_work(), reason="no systemd user manager (CI runners have none)"
)
def test_scoped_run_runs_and_logs(tmp_path):
    rc = scope.scoped_run(
        ["bash", "-c", "echo hello; exit 3"],
        what="t",
        memory_max="256M",
        cwd=tmp_path,
        log=tmp_path / "l.log",
        timeout_s=60,
    )
    assert rc == 3 and "hello" in (tmp_path / "l.log").read_text()


def test_cached_version_probes_once_per_key(monkeypatch):
    monkeypatch.setattr(scope, "_VERSIONS", {})
    calls = []

    def probe() -> str:
        calls.append(1)
        return "tool 1.0"

    assert scope.cached_version("k", probe) == "tool 1.0"
    assert scope.cached_version("k", probe) == "tool 1.0"
    assert calls == [1]


def test_cached_version_never_caches_a_failure(monkeypatch):
    monkeypatch.setattr(scope, "_VERSIONS", {})

    def bad() -> str:
        raise RuntimeError("no tool")

    with pytest.raises(RuntimeError):
        scope.cached_version("k", bad)
    assert scope.cached_version("k", lambda: "ok") == "ok"


def test_run_in_group_times_out_and_raises(tmp_path):
    from xut.container import RunTimeout

    with pytest.raises(RunTimeout, match="timeout after 1s"):
        scope.run_in_group(["sleep", "30"], cwd=tmp_path, log=tmp_path / "l", timeout_s=1)
