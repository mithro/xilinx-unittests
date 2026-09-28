# SPDX-License-Identifier: Apache-2.0
"""The harness in simulation (spec §7.1): Icarus in the xut-sim container, or xsim on the
host (Vivado sourced only in a subshell, via xut.runners.xsim.render_script).

``simulate`` builds one harness with the given slots, plays a host script into its UART
(``xut_hw_tb.sv``) and returns what the harness transmitted. ``sim_case`` (Task 5b) runs
every hardware-renderable configuration of a vector test through the simulated harness,
with the golden expected traces as the reference: the proof, before any board is
involved, that the harness, its compiler and its protocol reproduce the golden ``.xtr``.

The testbench also observes the harness (``SimResult``):

- ``margin_violations``: any in_vec or clock change closer than the monitor's bound to
  the previous change, and any capture closer than it to the last change. A capture is
  measured at the physical capture into ``cur_out``, two cycles before ``sample_take``'s
  edge (``xut_hw_ctrl``'s strobe timing), so the gap is not overstated.
- ``x_samples``: a sample whose captured bits hold an X or Z. The printer prints such a
  bit as ``0`` (the RTL has no simulator ifdefs), so without this an X from a UNISIM DUT
  would pass silently; it is the evidence of an ``x-dependence`` finding.
- An X or Z in a byte the harness transmits is a harness error (``HwSimError``).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from xut import container
from xut.container import executor_for
from xut.errors import XutError
from xut.hw.image import MARGIN, MAXWORDS
from xut.hw.slots import HW_HDL, HW_INCLUDES, HW_SOURCES, SlotBuild, render_cfg_vh, render_slots
from xut.hw.steps import Step, split_replies
from xut.modelsrc import ModelSource
from xut.runners.xsim import render_script
from xut.scope import OOM_RCS, scoped_run
from xut.slots import slot_count, vivado_slot

SIM_BUILD_ID = 0x51AB0001  # simulation has no bitstream; any fixed value
#: The one memory cap of `xut hw sim`: its command scope, and each xsim run (Global Constraints).
HW_SIM_MEMORY_MAX = "16G"
CPB = 4  # xut_hw_tb.sv's UART clocks per bit
TB = "xut_hw_tb.sv"


def max_sim_jobs(sim: str) -> int:
    """The most parallel simulations the memory budget allows, after the command's own
    ``HW_SIM_MEMORY_MAX`` scope is taken out of it. Icarus jobs are containers:
    (budget - 16G) // the container cap (21 at 100g and 4g). xsim jobs are scopes of
    ``HW_SIM_MEMORY_MAX`` each, and each holds a Vivado slot: min((budget - 16G) // 16G,
    the slot count) (min(5, 4) = 4 at the defaults)."""
    budget = container.size_bytes(
        os.environ.get(container.BUDGET_ENV, container.DEFAULT_BUDGET),
        f"${container.BUDGET_ENV}",
    )
    scope = container.size_bytes(HW_SIM_MEMORY_MAX.lower(), "HW_SIM_MEMORY_MAX")
    left = budget - scope
    if sim == "iverilog":
        cap = container.size_bytes(container.container_memory(), f"${container.MEMORY_ENV}")
        return max(1, left // cap)
    return max(1, min(left // scope, slot_count()))


class HwSimError(XutError, RuntimeError):
    """The simulated harness did not compile, did not finish, or answered malformed."""


def render_host(steps: Sequence[Step]) -> tuple[str, int]:
    """``host.memh`` for ``steps`` and its word count. After each step's bytes the host
    waits until the harness has sent every reply line so far: one command in flight
    (``xut.hw.steps``)."""
    words: list[int] = []
    nl = 0
    for s in steps:
        words += list(s.send)
        nl += s.lines
        words.append((1 << 28) | nl)
    words.append(0xF << 28)
    return "".join(f"{w:08x}\n" for w in words), len(words)


@dataclass
class SimResult:
    tx: bytes
    replies: list[bytes]
    log: Path
    margin_violations: list[str]
    x_samples: list[str] = field(default_factory=list)


def _iverilog(d: Path, files: list[str], ms: ModelSource, work_root: Path, timeout_s: int) -> str:
    ex = executor_for(ms, work_root)
    libs = [a for p in ms.search for a in ("-y", ex.guest(p))]
    comp = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_hw_tb", "-s", "glbl", "-I", "."]
    comp += [*libs, "-Y", ".v", *files, ex.guest(ms.glbl)]
    log = d / "run.log"
    if ex.run(comp, cwd=d, log=log, timeout_s=timeout_s) != 0:
        raise HwSimError(f"iverilog: the harness did not compile (see {log})")
    ex.run(["vvp", "-n", "sim.vvp"], cwd=d, log=log, timeout_s=timeout_s)
    return log.read_text(errors="replace")


def _xsim(d: Path, files: list[str], timeout_s: int) -> str:
    """xsim through ``scoped_run`` at ``HW_SIM_MEMORY_MAX``, inside a host-wide
    ``vivado_slot()`` (Vivado sourced only in ``xsim.sh``'s subshell, as in the xsim
    runner)."""
    (d / "xsim.sh").write_text(render_script(d, files, "xut_hw_tb", [], {}, {}))
    log = d / "run.log"
    log.write_text("")
    with vivado_slot():  # host-wide bound on Vivado/xsim processes (PR #10)
        rc = scoped_run(
            ["bash", "xsim.sh"],
            what="hwsim-xsim",
            memory_max=HW_SIM_MEMORY_MAX,
            cwd=d,
            log=log,
            timeout_s=timeout_s,
        )
    if rc in OOM_RCS:
        raise HwSimError(f"xsim: killed at the {HW_SIM_MEMORY_MAX} scope cap, rc {rc} (see {log})")
    return log.read_text(errors="replace")


def simulate(
    slots: Sequence[SlotBuild],
    steps: Sequence[Step],
    sim: str,
    workdir: Path,
    *,
    model_source: ModelSource,
    work_root: Path,
    extra_files: Sequence[Path] = (),
    maxwords: int = MAXWORDS,
    margin: int = MARGIN,
    monitor_margin: int | None = None,
    timeout_s: int = 1800,
) -> SimResult:
    """``monitor_margin`` (default ``margin``) is the testbench monitor's bound; a larger
    one lets a test prove the monitor measures what it claims."""
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    for f in (*HW_SOURCES, *HW_INCLUDES, TB):
        shutil.copy(HW_HDL / f, workdir / f)
    for f in extra_files:
        shutil.copy(f, workdir / Path(f).name)
    (workdir / "xut_hw_slots.v").write_text(render_slots(slots))
    (workdir / "xut_hw_cfg.vh").write_text(render_cfg_vh(slots, SIM_BUILD_ID, maxwords, margin))
    memh, n = render_host(steps)
    (workdir / "host.memh").write_text(memh)
    mon = margin if monitor_margin is None else monitor_margin
    (workdir / "host.vh").write_text(
        f"// SPDX-License-Identifier: Apache-2.0\n`define XUT_HOST_WORDS {n}\n"
        f"`define XUT_HW_TB_CPB {CPB}\n`define XUT_HW_TB_MON_MARGIN {mon}\n"
    )
    files = [*HW_SOURCES, "xut_hw_slots.v", *(Path(f).name for f in extra_files), TB]
    if sim == "iverilog":
        text = _iverilog(workdir, files, model_source, work_root, timeout_s)
    elif sim == "xsim":
        text = _xsim(workdir, files, timeout_s)
    else:
        raise HwSimError(f"unknown simulator {sim!r} (iverilog or xsim)")
    log = workdir / "run.log"
    if "XUT_DONE" not in text:
        why = "timed out" if "XUT_TIMEOUT" in text else "did not finish"
        raise HwSimError(f"{sim}: the harness testbench {why} (see {log})")
    x_tx = [ln.strip() for ln in text.splitlines() if "XUT_X_TX" in ln]
    if x_tx:
        raise HwSimError(f"{sim}: the harness transmitted X/Z: {x_tx[0]} (see {log})")
    tx = bytes(int(x, 16) for x in (workdir / "harness_tx.txt").read_text().split())
    viol = [ln.strip() for ln in text.splitlines() if "XUT_MARGIN_VIOLATION" in ln]
    xs = [ln.strip() for ln in text.splitlines() if "XUT_X_SAMPLE" in ln]
    return SimResult(tx, split_replies(tx, steps), log, viol, xs)
