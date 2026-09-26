# SPDX-License-Identifier: Apache-2.0
"""In-container cocotb launcher (spec §4.3 cocotb style). Runs with the image's python3,
where cocotb 2.0.1 is installed and xut's own dependencies are not::

    python3 cocotb_run.py --sim icarus|verilator --work <cfgdir> --module <stem>
        --test-dir <dir> --unisims <dir> [--retarget <dir>] [--lib-first <dir>]...
        --glbl <file> --seed N [--x-seed N] [--define K[=V]]... [--shared <dir>]...

It builds ``<work>/dut/xut_dut.v`` + ``xut_cocotb_top.v`` + glbl with
``cocotb_tools.runner`` (top ``xut_cocotb_top``, which instantiates glbl itself, so the
runner's ``glbl_instance`` strategy does not apply), runs test module ``<stem>`` with
cocotb's ``RANDOM_SEED`` = ``--seed`` and ``test_dir`` = ``<work>``, and exits 0 iff
``<work>/results.xml`` records at least one test and no failure; a failed HDL build
exits ``BUILD_FAILED`` (3) without running any test. The calling runner
classifies the run from ``results.xml`` itself (``xut.runners.sim.cocotb_check``).

``--lib-first`` directories are searched before UNISIM (the verilatorized models, for
Verilator and iverilog-vz). ``--x-seed`` is Verilator's X-initialisation seed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TOP = "xut_cocotb_top"
#: Exit code when the HDL build fails (no test ran); the runner reports ``compile failed``.
#: Keep equal to ``xut.runners.sim.COCOTB_BUILD_FAILED`` (pinned by test_runner_cocotb).
BUILD_FAILED = 3


def build_args(sim: str, unisims: str, retarget: str | None, lib_first: list[str]) -> list[str]:
    """The simulator-specific compile arguments: library search path first."""
    libs = [*lib_first, unisims, *([retarget] if retarget else [])]
    if sim == "icarus":
        return [*(a for d in libs for a in ("-y", d)), "-Y", ".v"]
    # as the verilator runner's own builds: warnings stay in the log, none is fatal
    return [
        "--timing",
        "-Wno-fatal",
        "--x-assign",
        "unique",
        "--x-initial",
        "unique",
        *(a for d in libs for a in ("-y", d)),
        "+libext+.v",
    ]


def plusargs(sim: str, x_seed: int | None) -> list[str]:
    """Run-time plusargs: Verilator's X-initialisation seed, nothing for Icarus."""
    if sim != "verilator":
        return []
    if x_seed is None:
        raise SystemExit("cocotb_run: --x-seed is required with --sim verilator")
    if x_seed <= 0:  # +verilator+seed+0 means "pick a random seed": never reproducible
        raise SystemExit(f"cocotb_run: --x-seed must be > 0 (got {x_seed})")
    return [f"+verilator+seed+{x_seed}", "+verilator+rand+reset+2"]


def defines(items: list[str]) -> dict[str, object]:
    """``K`` or ``K=V`` -> ``{K: V}`` (``K`` alone is defined as 1)."""
    out: dict[str, object] = {}
    for it in items:
        k, eq, v = it.partition("=")
        out[k] = v if eq else 1
    return out


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cocotb_run.py", description=__doc__.splitlines()[0])
    p.add_argument("--sim", choices=("icarus", "verilator"), required=True)
    p.add_argument("--work", required=True, help="configuration directory")
    p.add_argument("--module", required=True, help="cocotb test module (file stem)")
    p.add_argument("--test-dir", required=True, help="directory holding <module>.py")
    p.add_argument("--unisims", required=True)
    p.add_argument("--retarget")
    p.add_argument("--lib-first", action="append", default=[])
    p.add_argument("--glbl", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--x-seed", type=int)
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--shared", action="append", default=[])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    from cocotb_tools.check_results import get_results
    from cocotb_tools.runner import get_runner

    work = Path(a.work).resolve()
    # The test module and the unit's shared code must be importable by the simulator's
    # embedded Python: put them on PYTHONPATH (which the simulator process inherits).
    path = [a.test_dir, *a.shared, *filter(None, os.environ.get("PYTHONPATH", "").split(":"))]
    os.environ["PYTHONPATH"] = ":".join(dict.fromkeys(path))
    plus = plusargs(a.sim, a.x_seed)
    runner = get_runner(a.sim)
    build_dir = work / "sim_build"
    try:
        runner.build(
            sources=[work / "dut/xut_dut.v", work / "dut/xut_cocotb_top.v", a.glbl],
            includes=[work / "dut"],
            defines=defines(a.define),
            hdl_toplevel=TOP,
            build_args=build_args(a.sim, a.unisims, a.retarget, a.lib_first),
            timescale=("1ps", "1ps"),
            build_dir=build_dir,
            always=True,
        )
    except subprocess.CalledProcessError as e:  # the compiler's output is already logged
        print(f"XUT_COCOTB build failed: exit status {e.returncode}", flush=True)
        return BUILD_FAILED
    print(f"XUT_COCOTB plusargs: {' '.join(plus) or '(none)'}", flush=True)
    results = runner.test(
        test_module=a.module,
        hdl_toplevel=TOP,
        seed=a.seed,
        build_dir=build_dir,
        test_dir=work,
        plusargs=plus,
        results_xml=str(work / "results.xml"),
    )
    total, failed = get_results(results)
    print(f"XUT_COCOTB total={total} failed={failed} seed={a.seed}", flush=True)
    return 0 if total and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
