# SPDX-License-Identifier: Apache-2.0
"""The RTL harness transmits byte for byte what the reference emulator predicts, on
Icarus (container) and on xsim (Vivado), error paths included (Task 5a); and the
simulated harness reproduces the golden traces of real flops (Task 5b)."""

import pytest
from hw_toy import TOYFF_V, ToyDff, toy_map, toy_spec

from xut.hw import proto
from xut.hw.compile import compile_program
from xut.hw.hwsim import SIM_BUILD_ID, simulate
from xut.hw.image import MARGIN, MAXWORDS, W_END, W_SAMPLE, HwProgram, w_commit, w_set
from xut.hw.interp import EmuSlot, Harness
from xut.hw.replay import ModelDut
from xut.hw.selftest import CounterSim, PassthroughSim, selftest_programs
from xut.hw.slots import SELFTEST_SLOTS, SlotBuild, dut_slot
from xut.hw.steps import Step, run_replies, session_steps
from xut.modelsrc import resolve
from xut.stimgen import VecBuilder
from xut.wrap import render_wrapper

SIMS = [
    pytest.param("iverilog", marks=pytest.mark.container),
    pytest.param("xsim", marks=pytest.mark.vivado),
]


def _toy(init: int, d0: int):
    cfg = f"i{init}d{d0}"
    m = toy_map(cfg, init)
    b = VecBuilder(m, seed=5)
    if d0:
        b.init(D=1)
    b.sample("p")  # power-on: Q = INIT
    b.cycle("C")  # captures the power-on D (t0)
    for d in (0, 1, 1, 0):
        b.set(D=d)
        b.cycle("C")
    vec = b.build()
    prog = compile_program(vec, m)
    return m, prog, dut_slot(m, render_wrapper(toy_spec(cfg, init), m), prog.t0), vec


#: A 20-bit (two-chunk) DUT, out_vec = ~in_vec, no clock: the RTL's multi-chunk path
#: (Task 4 review, Minor 1).
WIDE_WRAPPER = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module xut_dut (
  input  wire [0:0]  clk,
  input  wire [19:0] in_vec,
  output wire [19:0] out_vec
);
  assign out_vec = ~in_vec;
endmodule
"""
WIDE_T0 = "1010" * 5
WIDE = SlotBuild("dut", 20, 20, 0, WIDE_T0, WIDE_WRAPPER, "LUT1")
#: Both chunks at once (chunk 1's 0xFFF5 is truncated to the slot's 4 bits on COMMIT),
#: then a SET to a chunk the harness does not have (MAXIN 32: no chunk 2) with a chunk-1
#: change.
WIDE_PROG = HwProgram(
    20,
    0,
    20,
    WIDE_T0,
    (
        W_SAMPLE,
        w_set(0, 0x1234),
        w_set(1, 0xFFF5),
        w_commit(),
        W_SAMPLE,
        w_set(2, 0xFFFF),
        w_set(1, 0x000A),
        w_commit(),
        W_SAMPLE,
        W_END,
    ),
    ("t0", "both", "chunk1"),
)


class InvertSim:
    def reset(self, t0: str) -> None:
        self._v = t0

    def drive(self, in_bits: str, clk_bits: str) -> None:
        self._v = in_bits

    def out_bits(self) -> str:
        return "".join("1" if c == "0" else "0" for c in self._v)


#: The error-path steps ``_steps`` puts before the normal session.
N_ERROR_STEPS = 4


def _steps(progs):
    """The normal session, preceded and followed by every error path."""
    t2 = progs[2]
    bad_crc = bytearray(proto.load_frame(2, t2.words))
    bad_crc[-1] ^= 0xFF
    pre = [
        Step(proto.CMD_RUN, 2),  # noload
        Step(b"Z", 1),  # badcmd
        Step(bytes(bad_crc), 1),  # badcrc
        Step(proto.load_frame(9, [W_END]), 1),  # badslot
    ]
    post = [Step(proto.load_frame(2, t2.words), 1), Step(proto.CMD_RUN, 2)]  # used
    assert len(pre) == N_ERROR_STEPS
    return pre + session_steps(progs) + post


@pytest.mark.parametrize("sim", SIMS)
def test_rtl_matches_the_emulator_byte_for_byte(sim, tmp_path):
    a, b = _toy(0, 1), _toy(1, 0)
    slots = (*SELFTEST_SLOTS, a[2], b[2], WIDE)
    progs = {**selftest_programs(), 2: a[1], 3: b[1], 4: WIDE_PROG}
    steps = _steps(progs)
    r = simulate(
        slots,
        steps,
        sim,
        tmp_path / "sim",
        model_source=resolve("auto"),
        work_root=tmp_path,
        extra_files=(TOYFF_V,),
    )
    emu = Harness(
        SIM_BUILD_ID,
        [
            EmuSlot(16, 16, 0, "0" * 16, PassthroughSim()),
            EmuSlot(2, 8, 1, "00", CounterSim()),
            EmuSlot(1, 1, 1, a[1].t0, ModelDut(ToyDff, a[3].attrs, a[0])),
            EmuSlot(1, 1, 1, b[1].t0, ModelDut(ToyDff, b[3].attrs, b[0])),
            EmuSlot(20, 20, 0, WIDE_T0, InvertSim()),
        ],
        margin=MARGIN,
        maxwords=MAXWORDS,
    )
    expected = b"".join(emu.feed(s.send) for s in steps)  # one command in flight
    assert r.margin_violations == []
    assert r.x_samples == []
    assert r.tx == expected
    session = r.replies[N_ERROR_STEPS : N_ERROR_STEPS + len(session_steps(progs))]
    runs = run_replies(session, progs)
    toy_run = runs[2]
    assert toy_run.status == 0 and toy_run.samples[0] == "0"  # power-on Q = INIT = 0
    assert toy_run.samples[1] == "1"  # the first edge captured the power-on D = t0 = 1
    wide = runs[4]
    assert wide.status == 0
    assert wide.samples == ("01010101010101010101", "10101110110111001011", "01011110110111001011")


#: A DUT whose output is X: the testbench must flag it (the printer prints X as 0).
X_WRAPPER = """// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module xut_dut (
  input  wire [0:0] clk,
  input  wire [0:0] in_vec,
  output wire [0:0] out_vec
);
  assign out_vec = 1'bx;
endmodule
"""


@pytest.mark.container
def test_the_testbench_flags_x_samples_and_measures_the_physical_capture(tmp_path):
    """Both monitor branches are live and measure what the ``xut_hw_ctrl`` strobe timing
    says. With a bound of MARGIN + 4, the capture branch (timed at the physical capture
    into ``cur_out``, sample_take - 2) flags the COMMIT/EDGE-then-SAMPLE gaps, the
    shortest being exactly MARGIN + 1; the change branch flags the counter's back-to-back
    EDGEs at exactly MARGIN + 3. And an X reaching ``cur_out`` at a sample is reported,
    not silently printed as 0."""
    xslot = SlotBuild("dut", 1, 1, 0, "0", X_WRAPPER, "LUT1")
    xprog = HwProgram(1, 0, 1, "0", (W_SAMPLE, W_END), ("x",))
    progs = {**selftest_programs(), 2: xprog}
    bound = MARGIN + 4
    r = simulate(
        (*SELFTEST_SLOTS, xslot),
        session_steps(progs),
        "iverilog",
        tmp_path / "sim",
        model_source=resolve("auto"),
        work_root=tmp_path,
        monitor_margin=bound,
    )

    def gaps(kind: str) -> set[int]:
        return {
            int(v.rsplit("gap=", 1)[1])
            for v in r.margin_violations
            if v.startswith(f"XUT_MARGIN_VIOLATION {kind} ")
        }

    assert min(gaps("capture")) == MARGIN + 1 and max(gaps("capture")) < bound
    assert gaps("change") == {MARGIN + 3}, r.margin_violations
    assert len(r.x_samples) == 1 and "x" in r.x_samples[0].split("bits=")[1], r.x_samples
    assert run_replies(r.replies, progs)[2].samples == ("0",)  # what the printer made of X


@pytest.mark.container
def test_a_short_reply_ends_the_simulation_with_the_partial_reply(tmp_path):
    """A step that expects more lines than the harness sends (an early ``end``, a wrong
    label count) ends the run once the harness is idle, in seconds, not at the outer
    timeout, and the error carries every byte that did arrive."""
    from xut.hw.hwsim import HwSimError

    with pytest.raises(HwSimError, match="short reply") as ei:
        simulate(
            SELFTEST_SLOTS,
            [Step(proto.CMD_ID, 2)],
            "iverilog",
            tmp_path / "sim",
            model_source=resolve("auto"),
            work_root=tmp_path,
            timeout_s=120,
        )
    assert ei.value.tx == proto.render(
        "id", build=SIM_BUILD_ID, slots=2, maxwords=MAXWORDS, margin=MARGIN
    )
    assert "step 0" in str(ei.value)


def test_render_host_waits_for_each_whole_reply():
    """One command in flight: after each step's bytes the host waits until the harness has
    sent every line of the reply so far."""
    from xut.hw.hwsim import render_host

    memh, n = render_host([Step(b"I", 1), Step(b"R", 3)])
    assert memh.split() == ["00000049", "10000001", "00000052", "10000004", "f0000000"]
    assert n == 5


def test_hw_sim_jobs_are_capped_by_the_budget(monkeypatch):
    from xut.hw import hwsim

    monkeypatch.delenv("XUT_MEMORY_BUDGET", raising=False)
    monkeypatch.delenv("XUT_CONTAINER_MEMORY", raising=False)
    monkeypatch.delenv("XUT_VIVADO_SLOTS", raising=False)
    assert hwsim.max_sim_jobs("iverilog") == 21  # (100g - the 16G scope) // 4g
    assert hwsim.max_sim_jobs("xsim") == 4  # min((100g - 16G) // 16G = 5, 4 slots)
    monkeypatch.setenv("XUT_VIVADO_SLOTS", "8")
    assert hwsim.max_sim_jobs("xsim") == 5


def test_the_xsim_runner_script_runs_inside_a_vivado_slot(tmp_path, monkeypatch):
    """The rewritten `run_script` keeps PR #10's host-wide slot around xsim."""
    from contextlib import contextmanager

    from xut.runners import xsim

    held = []

    @contextmanager
    def slot():
        held.append(True)
        yield
        held.pop()

    def fake_group(argv, *, cwd, log, timeout_s, mode="a"):
        assert held, "xsim.sh ran outside a vivado_slot()"
        return 0

    monkeypatch.setattr(xsim, "vivado_slot", slot)
    monkeypatch.setattr(xsim, "run_in_group", fake_group)
    assert xsim.run_script(tmp_path, 10) == 0


def test_hw_sim_xsim_runs_inside_a_vivado_slot(tmp_path, monkeypatch):
    """Every xsim run of `xut hw sim` takes one of PR #10's host-wide slots."""
    from contextlib import contextmanager

    from xut.hw import hwsim

    held = []

    @contextmanager
    def slot():
        held.append(True)
        yield
        held.pop()

    def fake_run(argv, *, what, memory_max, cwd, log, timeout_s):
        assert held, "xsim ran outside a vivado_slot()"
        assert memory_max == hwsim.HW_SIM_MEMORY_MAX
        return 0

    monkeypatch.setattr(hwsim, "vivado_slot", slot)
    monkeypatch.setattr(hwsim, "scoped_run", fake_run)
    hwsim._xsim(tmp_path, ["a.sv"], 10)


def test_an_oom_killed_xsim_run_is_an_error(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from xut.hw import hwsim

    monkeypatch.setattr(hwsim, "vivado_slot", nullcontext)
    monkeypatch.setattr(hwsim, "scoped_run", lambda argv, **kw: 137)
    with pytest.raises(hwsim.HwSimError, match="scope cap"):
        hwsim._xsim(tmp_path, ["a.sv"], 10)


def test_an_oom_killed_vvp_run_is_an_error(tmp_path, monkeypatch):
    from xut.hw import hwsim

    class FakeEx:
        def guest(self, p):
            return str(p)

        def run(self, argv, cwd, log, timeout_s):
            log.write_text("")
            return 137 if argv[0] == "vvp" else 0

    monkeypatch.setattr(hwsim, "executor_for", lambda ms, root: FakeEx())
    with pytest.raises(hwsim.HwSimError, match="memory cap"):
        hwsim._iverilog(tmp_path, ["a.sv"], resolve("auto"), tmp_path, 10)
