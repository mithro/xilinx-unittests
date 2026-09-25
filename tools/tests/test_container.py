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


needs_image = pytest.mark.skipif(
    shutil.which("docker") is None or image_digest(SIM_IMAGE) is None,
    reason=f"{SIM_IMAGE} not built (run: uv run xut container build)",
)


@pytest.mark.container
@needs_image
def test_pinned_versions(tmp_path):
    from xut.container import sim_tool_versions

    work = repo_root() / "build" / "versions"
    v = sim_tool_versions(DockerExecutor(root=repo_root()), work)
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
@needs_image
@pytest.mark.parametrize("sim", ["icarus", "verilator"])
def test_cocotb_smoke_runs(sim):
    """cocotb 2.0.1 must run on both simulators (spec §4.3; Verilator v5.048, spec rev 3.1)."""
    work = repo_root() / "build" / "cocotb-smoke"
    work.mkdir(parents=True, exist_ok=True)
    (work / "smoke_dff.v").write_text(SMOKE_V)
    (work / "cocotb_smoke.py").write_text(SMOKE_TEST)
    (work / "smoke_run.py").write_text(SMOKE_RUN)
    log = work / f"{sim}.log"
    log.unlink(missing_ok=True)
    rc = DockerExecutor(root=repo_root()).run(
        ["python3", "smoke_run.py", sim],
        cwd=work,
        log=log,
        timeout_s=600,
        env={"PYTHONPATH": "."},
    )
    assert rc == 0, log.read_text()
    assert "XUT_COCOTB total=1 failed=0" in log.read_text()


@pytest.mark.container
@needs_image
def test_verilator_still_rejects_procedural_deassign(tmp_path):
    """Pins why `xut verilatorize` (spec §6.2) exists. If Verilator ever accepts the
    Verilog-1995 procedural assign/deassign, stop and raise it with the owner before Task 12."""
    work = repo_root() / "build" / "vl-deassign"
    work.mkdir(parents=True, exist_ok=True)
    (work / "toy.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\n"
        "module toy (input c, input d, input clr, output q);\n"
        "  reg r;\n  assign q = r;\n"
        "  always @(clr) if (clr) assign r = 1'b0; else deassign r;\n"
        "  always @(posedge c) r <= d;\nendmodule\n"
    )
    log = work / "lint.log"
    log.unlink(missing_ok=True)
    rc = DockerExecutor(root=repo_root()).run(
        ["verilator", "--lint-only", "toy.v"], cwd=work, log=log, timeout_s=120
    )
    assert rc != 0 and "deassign" in log.read_text()
