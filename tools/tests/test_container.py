# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.container: the pinned xut-sim image and the executors.

The `container`-marked tests need the image built (`uv run xut container build`) and are
skipped, with that reason, when it is not."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from xut import container
from xut.container import (
    SIM_IMAGE,
    DockerExecutor,
    Mount,
    NativeExecutor,
    RunTimeout,
    executor_for,
    image_digest,
)
from xut.modelsrc import ModelSource
from xut.paths import repo_root


def test_docker_argv_maps_paths(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    root = repo_root()
    ex = DockerExecutor(root=root, mounts=(Mount(Path("/opt/m"), "/models/m"),))
    work = root / "build" / "x"
    rc = ex.run(["iverilog", "-V"], cwd=work, log=tmp_path / "l.log", timeout_s=5)
    assert rc == 0
    argv = calls[0]
    assert argv[:2] == ["docker", "run"]
    assert "--rm" not in argv  # removed by `run` after its OOM check (Ruling S48)
    assert "--network=none" in argv
    assert f"{root}:/work" in argv
    assert "/opt/m:/models/m:ro" in argv
    assert argv[argv.index("-w") + 1] == "/work/build/x"
    # the in-container timeout (S48a M-2): an orphaned container still ends
    assert argv[argv.index(SIM_IMAGE) + 1 :] == [
        "nice", "-n", "19", "timeout", "-k", "10", "35", "iverilog", "-V",
    ]  # fmt: skip
    assert f"{os.getuid()}:{os.getgid()}" in argv
    assert "iverilog -V" in (tmp_path / "l.log").read_text()


def test_docker_env_passed(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 3),
    )
    ex = DockerExecutor(root=repo_root())
    rc = ex.run(["x"], cwd=repo_root(), log=tmp_path / "l.log", timeout_s=5, env={"A": "1"})
    assert rc == 3
    argv = calls[0]
    assert argv[argv.index("-w") + 1] == "/work"
    assert "A=1" in argv


def test_guest_paths(tmp_path):
    root = repo_root()
    ex = DockerExecutor(root=root, mounts=(Mount(tmp_path, "/models/m"),))
    assert ex.guest(root) == "/work"
    assert ex.guest(root / "a" / "b.v") == "/work/a/b.v"
    assert ex.guest(tmp_path) == "/models/m"
    assert ex.guest(tmp_path / "unisims") == "/models/m/unisims"


def test_guest_path_outside_mounts_raises(tmp_path):
    ex = DockerExecutor(root=repo_root())
    with pytest.raises(ValueError, match="not visible in the container"):
        ex.guest(Path("/etc/passwd"))


def test_docker_timeout_kills_container(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ex = DockerExecutor(root=repo_root())
    with pytest.raises(RunTimeout, match="timeout after 5s"):
        ex.run(["sleep", "99"], cwd=repo_root(), log=tmp_path / "l.log", timeout_s=5)
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "kill", name]


def test_native_executor_identity(tmp_path):
    ex = NativeExecutor()
    assert ex.guest(tmp_path) == str(tmp_path)
    rc = ex.run(["true"], cwd=tmp_path, log=tmp_path / "t.log", timeout_s=5)
    assert rc == 0


def test_native_executor_appends_and_env(tmp_path):
    ex = NativeExecutor()
    log = tmp_path / "sub" / "t.log"
    ex.run(["sh", "-c", "echo one"], cwd=tmp_path, log=log, timeout_s=5)
    rc = ex.run(
        ["sh", "-c", 'echo "$XUT_T"; exit 4'],
        cwd=tmp_path,
        log=log,
        timeout_s=5,
        env={"XUT_T": "two"},
    )
    assert rc == 4
    text = log.read_text()
    assert "one\n" in text and "two\n" in text


def test_native_executor_timeout(tmp_path):
    with pytest.raises(RunTimeout):
        NativeExecutor().run(["sleep", "5"], cwd=tmp_path, log=tmp_path / "t.log", timeout_s=1)


def test_executor_for(tmp_path, monkeypatch):
    monkeypatch.delenv("XUT_NATIVE", raising=False)
    outside = ModelSource("unisim-2025.2", tmp_path)
    ex = executor_for(outside)
    assert isinstance(ex, DockerExecutor)
    assert ex.mounts == (Mount(tmp_path.resolve(), "/models/unisim-2025.2"),)
    assert ex.guest(tmp_path / "glbl.v") == "/models/unisim-2025.2/glbl.v"
    inside = ModelSource("unisim-gh-2020.1", repo_root() / "third_party")
    assert executor_for(inside).mounts == ()
    monkeypatch.setenv("XUT_NATIVE", "1")
    assert isinstance(executor_for(outside), NativeExecutor)


def test_executor_for_mounts_a_work_root_outside_the_repository(tmp_path, monkeypatch):
    """A run rooted outside the checkout (pytest's tmp_path) is mounted read-write at
    /xut-root; the model source keeps its own read-only mount, even inside that root."""
    monkeypatch.delenv("XUT_NATIVE", raising=False)
    ms = ModelSource("toy", tmp_path / "ms")
    ex = executor_for(ms, tmp_path)
    assert ex.mounts == (
        Mount((tmp_path / "ms").resolve(), "/models/toy"),
        Mount(tmp_path.resolve(), "/xut-root", ro=False),
    )
    assert ex.guest(tmp_path / "ms/glbl.v") == "/models/toy/glbl.v"
    assert ex.guest(tmp_path / "build/x") == "/xut-root/build/x"
    argv = ex.argv(["true"], tmp_path, "n", None)
    assert f"{tmp_path.resolve()}:/xut-root" in argv
    assert f"{(tmp_path / 'ms').resolve()}:/models/toy:ro" in argv
    # the repository itself is /work already: no extra mount
    inside = ModelSource("unisim-gh-2020.1", repo_root() / "third_party")
    assert executor_for(inside, repo_root() / "build").mounts == ()


@pytest.mark.parametrize("which", ["root", "home", "repo-parent"])
def test_executor_for_refuses_a_broad_work_root(tmp_path, monkeypatch, which):
    """The run root is mounted read-write: /, $HOME and repo ancestors are refused."""
    monkeypatch.delenv("XUT_NATIVE", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    root = {"root": Path("/"), "home": home, "repo-parent": repo_root().parent}[which]
    with pytest.raises(container.ContainerError, match="refusing to mount"):
        executor_for(ModelSource("toy", tmp_path / "ms"), root)


def test_image_digest_missing_image():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    assert image_digest("xut-sim:no-such-tag-ever") is None


def test_sim_tool_versions_first_line_and_cached(tmp_path, monkeypatch):
    class Fake:
        image = "fake:1"
        runs = 0

        def guest(self, path):
            return str(path)

        def run(self, argv, cwd, log, timeout_s, env=None):
            Fake.runs += 1
            banner = {"iverilog": "Icarus Verilog version 12.0 (stable) ()\n\nmore"}.get(
                argv[0], f"{argv[0]} 1.0"
            )
            with log.open("a") as f:
                f.write(f"$ {' '.join(argv)}\n{banner}\n")
            return 0

    monkeypatch.setattr(container, "_VERSIONS", {})
    v = container.sim_tool_versions(Fake(), tmp_path)
    assert v == {
        "iverilog": "Icarus Verilog version 12.0 (stable) ()",
        "verilator": "verilator 1.0",
        "cocotb": "cocotb-config 1.0",
    }
    assert container.sim_tool_versions(Fake(), tmp_path) == v
    assert Fake.runs == 3
    assert list(tmp_path.iterdir()) == []


@pytest.mark.container
def test_pinned_versions(tmp_path, monkeypatch):
    from xut.container import sim_tool_versions

    monkeypatch.setattr(container, "_VERSIONS", {})
    v = sim_tool_versions(DockerExecutor(root=tmp_path), tmp_path)
    assert v["iverilog"].startswith("Icarus Verilog version 12.0")
    assert v["verilator"].startswith("Verilator 5.048")
    assert v["cocotb"] == "2.0.1"


SMOKE_V = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module smoke_dff (input wire clk, input wire d, output reg q);
  always @(posedge clk) q <= #100 d;
endmodule
"""
SMOKE_TEST = """# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def smoke(dut):
    dut.clk.value = 0
    dut.d.value = 1
    await Timer(1, "ns")
    dut.clk.value = 1
    await Timer(1, "ns")
    assert int(dut.q.value) == 1
"""
SMOKE_RUN = """# SPDX-License-Identifier: Apache-2.0
import sys
from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

sim = sys.argv[1]
r = get_runner(sim)
args = ["--timing"] if sim == "verilator" else []
r.build(sources=["smoke_dff.v"], hdl_toplevel="smoke_dff", build_args=args,
        timescale=("1ps", "1ps"), build_dir=f"sim_{sim}")
res = r.test(hdl_toplevel="smoke_dff", test_module="cocotb_smoke", build_dir=f"sim_{sim}",
             test_dir=".")
total, failed = get_results(res)
print(f"XUT_COCOTB total={total} failed={failed}")
sys.exit(1 if failed or not total else 0)
"""


@pytest.mark.container
@pytest.mark.parametrize("sim", ["icarus", "verilator"])
def test_cocotb_smoke_runs(sim, tmp_path):
    """cocotb 2.0.1 must run on both simulators (spec §4.3; Verilator v5.048, spec rev 3.1)."""
    work = tmp_path
    (work / "smoke_dff.v").write_text(SMOKE_V)
    (work / "cocotb_smoke.py").write_text(SMOKE_TEST)
    (work / "smoke_run.py").write_text(SMOKE_RUN)
    log = work / f"{sim}.log"
    rc = DockerExecutor(root=tmp_path).run(
        ["python3", "smoke_run.py", sim],
        cwd=work,
        log=log,
        timeout_s=600,
        env={"PYTHONPATH": "."},
    )
    assert rc == 0, log.read_text()
    assert "XUT_COCOTB total=1 failed=0" in log.read_text()


@pytest.mark.container
def test_verilator_still_rejects_procedural_deassign(tmp_path):
    """Pins why `xut verilatorize` (spec §6.2) exists. If Verilator ever accepts the
    Verilog-1995 procedural assign/deassign, stop and raise it with the owner before Task 12."""
    work = tmp_path
    (work / "toy.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\n"
        "module toy (input c, input d, input clr, output q);\n"
        "  reg r;\n  assign q = r;\n"
        "  always @(clr) if (clr) assign r = 1'b0; else deassign r;\n"
        "  always @(posedge c) r <= d;\nendmodule\n"
    )
    log = work / "lint.log"
    rc = DockerExecutor(root=tmp_path).run(
        ["verilator", "--lint-only", "toy.v"], cwd=work, log=log, timeout_s=120
    )
    assert rc != 0 and "deassign" in log.read_text()


# --- CLI: xut container build / versions -------------------------------------------


def test_cli_container_build(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main

    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        kw["stdout"].write("#1 building\n")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(container, "image_digest", lambda image=SIM_IMAGE: "sha256:abc")
    monkeypatch.setattr("xut.paths.cache_dir", lambda: tmp_path)  # keep the real build log
    result = CliRunner().invoke(main, ["container", "build"])
    assert result.exit_code == 0, result.output
    assert calls == [["docker", "build", "-t", SIM_IMAGE, str(repo_root() / "containers/sim")]]
    assert f"{SIM_IMAGE} sha256:abc" in result.output
    assert (tmp_path / "container-build.log").read_text() == "#1 building\n"


def test_cli_container_build_failure_is_clean_error(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main

    monkeypatch.setattr("xut.paths.cache_dir", lambda: tmp_path)

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 2))
    result = CliRunner().invoke(main, ["container", "build"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "docker build failed (exit 2)" in result.output
    assert "container-build.log" in result.output


def test_cli_container_build_without_docker_is_clean_error(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main

    monkeypatch.setattr("xut.paths.cache_dir", lambda: tmp_path)

    def no_docker(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory", "docker")

    monkeypatch.setattr(subprocess, "run", no_docker)
    result = CliRunner().invoke(main, ["container", "build"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "docker" in result.output and "not found" in result.output


def test_cli_container_versions(monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main

    seen = []

    def fake_versions(ex, workdir):
        seen.append((ex, workdir))
        return {"iverilog": "Icarus Verilog version 12.0 (stable) ()", "cocotb": "2.0.1"}

    monkeypatch.setattr(container, "sim_tool_versions", fake_versions)
    result = CliRunner().invoke(main, ["container", "versions"])
    assert result.exit_code == 0, result.output
    assert result.output == "iverilog: Icarus Verilog version 12.0 (stable) ()\ncocotb: 2.0.1\n"
    assert isinstance(seen[0][0], DockerExecutor)
    assert seen[0][1] == repo_root() / "build"


def test_ci_builds_the_current_sim_image():
    """CI builds the image with build-push-action (layer cache); its tag must track
    SIM_IMAGE, or the `container` tests would silently skip in CI."""
    import yaml

    steps = yaml.safe_load((repo_root() / ".github/workflows/ci.yml").read_text())["jobs"]["sim"][
        "steps"
    ]
    builds = [s for s in steps if s.get("uses", "").startswith("docker/build-push-action@")]
    assert len(builds) == 1
    w = builds[0]["with"]
    assert w["tags"] == SIM_IMAGE
    assert w["context"] == "containers/sim"
    assert w["load"] is True
    assert w["cache-from"] == "type=gha" and w["cache-to"] == "type=gha,mode=max"


# --- A3/A4: failures are errors, never versions; no network pulls; kill timeouts


def test_docker_never_pulls(tmp_path):
    argv = DockerExecutor(root=tmp_path).argv(["true"], tmp_path, "n", None)
    assert "--pull=never" in argv and argv.index("--pull=never") < argv.index(SIM_IMAGE)


class _FakeEx:
    """An executor whose tools answer from ``answers`` = {tool: (rc, banner)}."""

    image = "fake:1"

    def __init__(self, answers):
        self.answers, self.runs = answers, 0

    def guest(self, path):
        return str(path)

    def run(self, argv, cwd, log, timeout_s, env=None):
        self.runs += 1
        rc, banner = self.answers.get(argv[0], (0, f"{argv[0]} 1.0"))
        with log.open("a") as f:
            f.write(f"$ {' '.join(argv)}\n{banner}\n")
        return rc


def test_sim_tool_versions_nonzero_exit_is_an_error_and_not_cached(tmp_path, monkeypatch):
    from xut.container import ContainerError
    from xut.errors import XutError

    monkeypatch.setattr(container, "_VERSIONS", {})
    bad = _FakeEx(
        {
            "iverilog": (1, "Icarus Verilog version 12.0 (stable) ()"),
            "verilator": (125, "Unable to find image 'fake:1' locally"),
        }
    )
    with pytest.raises(ContainerError, match="verilator.*exit 125.*Unable to find image") as ei:
        container.sim_tool_versions(bad, tmp_path)
    assert isinstance(ei.value, XutError)
    assert container._VERSIONS == {}  # a failure is never cached as a version
    good = _FakeEx({"iverilog": (1, "Icarus Verilog version 12.0 (stable) ()")})
    assert container.sim_tool_versions(good, tmp_path)["verilator"] == "verilator 1.0"


def test_sim_tool_versions_iverilog_needs_its_banner(tmp_path, monkeypatch):
    from xut.container import ContainerError

    monkeypatch.setattr(container, "_VERSIONS", {})
    ex = _FakeEx({"iverilog": (125, "docker: Error response from daemon")})
    with pytest.raises(ContainerError, match="iverilog"):
        container.sim_tool_versions(ex, tmp_path)


def test_sim_tool_versions_missing_image_names_container_build(tmp_path, monkeypatch):
    from xut.container import ContainerError

    monkeypatch.setattr(container, "_VERSIONS", {})
    monkeypatch.setattr(container, "image_digest", lambda image=SIM_IMAGE: None)
    ex = DockerExecutor(image="xut-sim:no-such-tag", root=tmp_path)
    with pytest.raises(ContainerError, match="xut container build"):
        container.sim_tool_versions(ex, tmp_path)


def test_cli_container_versions_failure_exits_nonzero(monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main
    from xut.container import ContainerError

    def boom(ex, workdir):
        raise ContainerError("xut-sim:1 is not built: run `uv run xut container build`")

    monkeypatch.setattr(container, "sim_tool_versions", boom)
    result = CliRunner().invoke(main, ["container", "versions"])
    assert result.exit_code == 1 and "xut container build" in result.output


def test_docker_kill_timeout_still_raises_run_timeout(tmp_path, monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    ex = DockerExecutor(root=tmp_path)
    with pytest.raises(RunTimeout, match="docker kill") as ei:
        ex.run(["sleep", "99"], cwd=tmp_path, log=tmp_path / "l.log", timeout_s=5)
    assert isinstance(ei.value.__cause__, subprocess.TimeoutExpired)


# --- Ruling S48: memory-capped containers, OOM kills detected ----------------------------


def test_docker_argv_caps_memory_at_4g_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    ex = DockerExecutor(root=tmp_path)
    assert ex.memory == "4g"
    argv = ex.argv(["true"], tmp_path, "n", None)
    assert "--memory=4g" in argv and "--memory-swap=4g" in argv
    assert argv.index("--memory=4g") < argv.index(SIM_IMAGE)


def test_docker_memory_from_env_and_constructor(tmp_path, monkeypatch):
    monkeypatch.setenv("XUT_CONTAINER_MEMORY", "2g")
    argv = DockerExecutor(root=tmp_path).argv(["true"], tmp_path, "n", None)
    assert "--memory=2g" in argv and "--memory-swap=2g" in argv
    assert "--memory=4g" not in argv
    argv = DockerExecutor(root=tmp_path, memory="512m").argv(["true"], tmp_path, "n", None)
    assert "--memory=512m" in argv and "--memory-swap=512m" in argv


@pytest.mark.parametrize(
    "bad",
    ["4G", "4gb", "", "g", "1.5g", "4 g", "-1g", "4t", "0g", "00g", "0m", "00m", "1k", "63m",
     "33g", "99999g", "32769m"],
)  # fmt: skip
def test_docker_memory_refuses_a_malformed_cap(tmp_path, monkeypatch, bad):
    from xut.errors import XutError

    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    with pytest.raises(XutError, match="memory"):
        DockerExecutor(root=tmp_path, memory=bad)
    monkeypatch.setenv("XUT_CONTAINER_MEMORY", bad)
    with pytest.raises(XutError, match="XUT_CONTAINER_MEMORY"):
        DockerExecutor(root=tmp_path)


def _fake_docker(calls, run_rc=0, oom="false", run_exc=None, rm_exc=None, exit_code=None):
    """A fake `subprocess.run`: `docker run` exits `run_rc` (or raises
    `run_exc(argv, timeout)`), `docker inspect` answers `oom` and the container's exit code
    (`exit_code`, default `run_rc`), `docker rm -f` raises `rm_exc` if given."""

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "run"]:
            if run_exc is not None:
                raise run_exc(argv, kw.get("timeout"))
            return subprocess.CompletedProcess(argv, run_rc)
        if argv[:2] == ["docker", "inspect"]:
            code = run_rc if exit_code is None else exit_code
            return subprocess.CompletedProcess(argv, 0, stdout=f"{oom} {code}\n", stderr="")
        if argv[:3] == ["docker", "rm", "-f"] and rm_exc is not None:
            raise rm_exc
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    return fake_run


def _name(calls):
    return calls[0][calls[0].index("--name") + 1]


def test_docker_oom_kill_is_logged_and_keeps_rc_137(tmp_path, monkeypatch):
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_rc=137, oom="true"))
    log = tmp_path / "l.log"
    rc = DockerExecutor(root=tmp_path).run(["simx"], cwd=tmp_path, log=log, timeout_s=5)
    assert rc == 137
    name = _name(calls)
    assert calls[1] == [
        "docker",
        "inspect",
        "-f",
        "{{.State.OOMKilled}} {{.State.ExitCode}}",
        name,
    ]
    assert calls[2] == ["docker", "rm", "-f", name]
    assert log.read_text().splitlines()[-1] == "xut-container: oom-killed at memory cap 4g"
    assert container.OOM_MARK in log.read_text()


def test_docker_oom_kill_of_a_child_process_is_logged_too(tmp_path, monkeypatch):
    """The kernel kills the largest process in the cgroup: a `bash` script survives it and
    exits 0, yet docker still reports OOMKilled=true (measured on docker 26.1)."""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_rc=0, oom="true"))
    log = tmp_path / "l.log"
    rc = DockerExecutor(root=tmp_path, memory="1g").run(
        ["bash", "x.sh"], cwd=tmp_path, log=log, timeout_s=5
    )
    assert rc == 0
    assert "xut-container: oom-killed at memory cap 1g\n" in log.read_text()


def test_docker_no_oom_no_line_and_container_removed(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_rc=3))
    log = tmp_path / "l.log"
    assert DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=log, timeout_s=5) == 3
    assert "oom-killed" not in log.read_text()
    assert calls[-1] == ["docker", "rm", "-f", _name(calls)]


def test_docker_timeout_still_removes_the_container(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_exc=subprocess.TimeoutExpired))
    with pytest.raises(RunTimeout):
        DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=tmp_path / "l", timeout_s=5)
    name = _name(calls)
    assert calls[1] == ["docker", "kill", name]
    assert calls[-1] == ["docker", "rm", "-f", name]


def test_docker_exception_still_removes_the_container(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    interrupt = lambda argv, timeout: KeyboardInterrupt()  # noqa: E731
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_exc=interrupt))
    with pytest.raises(KeyboardInterrupt):
        DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=tmp_path / "l", timeout_s=5)
    assert calls[-1] == ["docker", "rm", "-f", _name(calls)]


def test_docker_rm_failure_does_not_mask_the_result(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", _fake_docker(calls, run_rc=5, rm_exc=FileNotFoundError("docker"))
    )
    log = tmp_path / "l.log"
    assert DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=log, timeout_s=5) == 5
    assert "docker rm -f" in log.read_text()


@pytest.mark.container
def test_docker_oom_kill_is_detected_live(tmp_path):
    log = tmp_path / "oom.log"
    rc = DockerExecutor(root=tmp_path, memory="64m").run(
        ["python3", "-c", "a = bytearray(10**9)"], cwd=tmp_path, log=log, timeout_s=120
    )
    assert rc == 137, log.read_text()
    assert "xut-container: oom-killed at memory cap 64m" in log.read_text()


@pytest.mark.parametrize(
    ("cap", "nbytes"),
    [("64m", 64 << 20), ("4g", 4 << 30), ("32g", 32 << 30), ("32768m", 32 << 30),
     ("65536k", 64 << 20)],
)  # fmt: skip
def test_docker_memory_accepts_64m_to_32g(tmp_path, monkeypatch, cap, nbytes):
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    assert container.size_bytes(cap, "memory") == nbytes
    argv = DockerExecutor(root=tmp_path, memory=cap).argv(["true"], tmp_path, "n", None)
    assert f"--memory={cap}" in argv


def test_memory_cap_error_names_the_range(tmp_path):
    from xut.errors import XutError

    with pytest.raises(XutError, match="64m.*32g"):
        DockerExecutor(root=tmp_path, memory="0g")


@pytest.mark.parametrize(
    ("cap", "budget", "want"),
    [(None, None, 25), ("16g", None, 6), ("4g", "200g", 50), ("32g", "100g", 3),
     ("64m", "1g", 16)],
)  # fmt: skip
def test_max_jobs_is_the_budget_over_the_cap(monkeypatch, cap, budget, want):
    for env, v in (("XUT_CONTAINER_MEMORY", cap), ("XUT_MEMORY_BUDGET", budget)):
        if v is None:
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, v)
    n, b, c = container.max_jobs()
    assert n == want
    assert (b, c) == (budget or "100g", cap or "4g")


@pytest.mark.parametrize("bad", ["0g", "100G", "", "1k", "lots"])
def test_memory_budget_refuses_a_malformed_value(monkeypatch, bad):
    from xut.errors import XutError

    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    monkeypatch.setenv("XUT_MEMORY_BUDGET", bad)
    with pytest.raises(XutError, match="XUT_MEMORY_BUDGET"):
        container.max_jobs()


# --- S48a M-1/M-2: labels, in-container timeout, cleanup on interrupt, orphan sweep ------


def test_docker_argv_labels_every_container(tmp_path):
    argv = DockerExecutor(root=tmp_path).argv(["true"], tmp_path, "n", None)
    assert f"xut.host={container.host_id()}" in argv
    assert f"xut.owner={os.getpid()}" in argv
    assert f"xut.session={container.SESSION}" in argv
    assert argv[argv.index(f"xut.owner={os.getpid()}") - 1] == "--label"
    assert argv.index("--label") < argv.index(SIM_IMAGE)
    assert argv[-5:] == [SIM_IMAGE, "nice", "-n", "19", "true"]  # no in-container timeout


def test_docker_argv_in_container_timeout_outlasts_the_host_timeout(tmp_path):
    argv = DockerExecutor(root=tmp_path).argv(["x"], tmp_path, "n", None, timeout_s=600)
    assert argv[-5:] == ["timeout", "-k", "10", "630", "x"]


def test_docker_interrupted_inspect_still_removes_the_container(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "inspect"]:
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(KeyboardInterrupt):
        DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=tmp_path / "l", timeout_s=5)
    assert calls[-1] == ["docker", "rm", "-f", _name(calls)]
    assert _name(calls) not in container._LIVE


def test_docker_live_names_are_tracked_while_running(tmp_path, monkeypatch):
    seen: list[set[str]] = []

    def fake_run(argv, **kw):
        if argv[:2] == ["docker", "run"]:
            seen.append(set(container._LIVE))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(container, "_LIVE", set())
    DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=tmp_path / "l", timeout_s=5)
    assert len(seen) == 1 and len(seen[0]) == 1 and next(iter(seen[0])).startswith("xut-")
    assert not container._LIVE


def test_kill_live_kills_every_running_container(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[-1] == "xut-b":
            raise subprocess.TimeoutExpired(argv, 30)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(container, "_LIVE", {"xut-a", "xut-b"})
    assert sorted(container.kill_live()) == ["xut-a", "xut-b"]
    assert sorted(calls) == [["docker", "kill", "xut-a"], ["docker", "kill", "xut-b"]]
    monkeypatch.setattr(container, "_LIVE", set())
    calls.clear()
    assert container.kill_live() == [] and calls == []


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_sweep_orphans_removes_containers_of_dead_owners_only(monkeypatch):
    dead = _dead_pid()
    calls: list[list[str]] = []
    listing = f"c1\t{dead}\nc2\t{os.getpid()}\nc3\tnot-a-pid\n"

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(argv, 0, stdout=listing, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert container.sweep_orphans() == ["c1"]
    ps = calls[0]
    assert ps[:3] == ["docker", "ps", "-a"] and "label=xut.owner" in ps
    # only this host's (and this boot's) containers: a pid means nothing elsewhere (R-3)
    assert f"label=xut.host={container.host_id()}" in ps
    assert calls[1:] == [["docker", "rm", "-f", "c1"]]


def test_sweep_orphans_reports_rm_failures_once_at_the_end(monkeypatch):
    dead = _dead_pid()
    calls: list[list[str]] = []
    listing = f"c1\t{dead}\nc2\t{dead}\nc3\t{dead}\n"

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(argv, 0, stdout=listing, stderr="")
        if argv[-1] == "c2":
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="device busy")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(container.ContainerError) as ei:
        container.sweep_orphans()
    assert [c[-1] for c in calls[1:]] == ["c1", "c2", "c3"]  # never stops partway
    msg = str(ei.value)
    assert "removed 2" in msg and "c1" in msg and "c3" in msg
    assert "c2: device busy" in msg


def test_host_id_is_hostname_and_boot_id():
    import socket

    host, _, boot = container.host_id().partition(":")
    assert host == socket.gethostname()
    assert boot == Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def test_sweep_orphans_docker_failure_is_an_error(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="no daemon"),
    )
    with pytest.raises(container.ContainerError, match="no daemon"):
        container.sweep_orphans()


def test_doctor_sweep_containers(monkeypatch):
    from click.testing import CliRunner

    from xut.cli import main

    monkeypatch.setattr(container, "sweep_orphans", lambda: ["c1", "c9"])
    r = CliRunner().invoke(main, ["doctor", "--sweep-containers"])
    assert r.exit_code == 0, r.output
    assert "removed 2 orphaned xut container(s): c1, c9" in r.output
    monkeypatch.setattr(container, "sweep_orphans", lambda: [])
    r = CliRunner().invoke(main, ["doctor", "--sweep-containers"])
    assert "no orphaned xut containers" in r.output


# --- S48a R-1/R-2: an interrupt halts every later container; a budget below the cap ------


def test_budget_below_the_cap_is_a_clear_error(monkeypatch):
    from xut.errors import XutError

    monkeypatch.setenv("XUT_CONTAINER_MEMORY", "4g")
    monkeypatch.setenv("XUT_MEMORY_BUDGET", "2g")
    with pytest.raises(XutError, match="budget.*2g.*below the container cap 4g"):
        container.max_jobs()


def test_a_run_after_kill_live_refuses_to_start(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls))
    monkeypatch.setattr(container, "_LIVE", set())
    container.kill_live()
    log = tmp_path / "l.log"
    with pytest.raises(container.RunCancelled, match="interrupted"):
        DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=log, timeout_s=5)
    assert isinstance(container.RunCancelled("x"), KeyboardInterrupt)
    assert not any(c[:2] == ["docker", "run"] for c in calls)
    assert "interrupted" in log.read_text()
    assert not container._LIVE


def test_kill_live_misses_no_container_started_around_it(tmp_path, monkeypatch):
    """The add-versus-snapshot race (R-1): every `docker run` issued once the halt is set
    belongs to a container in kill_live's snapshot, and every later run refuses."""
    import random
    import threading
    import time

    started: list[tuple[str, bool]] = []
    guard = threading.Lock()

    def fake_run(argv, **kw):
        if argv[:2] == ["docker", "run"]:
            name = argv[argv.index("--name") + 1]
            with guard:
                started.append((name, container._HALT.is_set()))
            time.sleep(random.random() / 200)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(container, "_LIVE", set())
    ex = DockerExecutor(root=tmp_path)
    refused: list[int] = []

    def worker(i):
        while True:  # until the halt stops it
            try:
                ex.run(["x"], cwd=tmp_path, log=tmp_path / f"{i}.log", timeout_s=5)
            except container.RunCancelled:
                refused.append(i)
                return

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.02)
    killed = set(container.kill_live())
    for t in threads:
        t.join()
    late = [n for n, halted in started if halted]
    assert all(n in killed for n in late), (late, killed)
    assert len(refused) == 8  # every worker was stopped by the halt


def test_exit_137_without_oomkilled_is_an_inferred_oom_kill(tmp_path, monkeypatch):
    """Docker setups that never set State.OOMKilled (GitHub's runners): a container exit of
    137 with no xut timeout is still recorded as an OOM kill, marked as inferred."""
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_rc=137, oom="false"))
    log = tmp_path / "l.log"
    assert DockerExecutor(root=tmp_path).run(["simx"], cwd=tmp_path, log=log, timeout_s=5) == 137
    text = log.read_text()
    assert container.oom_line("4g") in text
    assert "inferred: exit 137" in text


def test_a_timeout_kill_is_never_inferred_to_be_an_oom_kill(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    timeout = lambda argv, t: subprocess.TimeoutExpired(argv, t)  # noqa: E731
    monkeypatch.setattr(
        subprocess, "run", _fake_docker(calls, run_exc=timeout, oom="false", exit_code=137)
    )
    log = tmp_path / "l.log"
    with pytest.raises(RunTimeout):
        DockerExecutor(root=tmp_path).run(["simx"], cwd=tmp_path, log=log, timeout_s=5)
    assert container.OOM_MARK not in log.read_text()


def test_a_clean_exit_is_never_an_oom_kill(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_docker(calls, run_rc=1, oom="false"))
    log = tmp_path / "l.log"
    assert DockerExecutor(root=tmp_path).run(["x"], cwd=tmp_path, log=log, timeout_s=5) == 1
    assert container.OOM_MARK not in log.read_text()


def test_docker_argv_low_priority(tmp_path, monkeypatch):
    """Host rule: every container gets 1/8 of docker's CPU weight, at most 2 CPUs
    (XUT_CONTAINER_CPUS) and runs its command under nice 19."""
    from xut import errors as xut_errors

    monkeypatch.delenv("XUT_CONTAINER_CPUS", raising=False)
    argv = DockerExecutor(root=tmp_path).argv(["x"], tmp_path, "n", None)
    img = argv.index(SIM_IMAGE)
    assert "--cpu-shares=128" in argv[:img] and "--cpus=2" in argv[:img]
    assert argv[img + 1 : img + 4] == ["nice", "-n", "19"]
    monkeypatch.setenv("XUT_CONTAINER_CPUS", "1.5")
    assert "--cpus=1.5" in DockerExecutor(root=tmp_path).argv(["x"], tmp_path, "n", None)
    for bad in ("0", "-1", "many"):
        monkeypatch.setenv("XUT_CONTAINER_CPUS", bad)
        with pytest.raises(xut_errors.XutError, match="XUT_CONTAINER_CPUS"):
            DockerExecutor(root=tmp_path).argv(["x"], tmp_path, "n", None)
