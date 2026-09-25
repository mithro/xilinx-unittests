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
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network=none" in argv
    assert f"{root}:/work" in argv
    assert "/opt/m:/models/m:ro" in argv
    assert argv[argv.index("-w") + 1] == "/work/build/x"
    assert argv[-2:] == ["iverilog", "-V"]
    assert argv[-3] == SIM_IMAGE
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
