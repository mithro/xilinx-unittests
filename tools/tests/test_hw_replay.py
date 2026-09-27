# SPDX-License-Identifier: Apache-2.0
"""The harness rendering of a stimulus, interpreted against the golden model, gives the
golden trace: the compiler and the interpreter preserve every behaviour the stepped
harness claims to preserve (spec §5.1 ruling S8')."""

from pathlib import Path

import pytest
from hw_toy import ToyDff, toy_map

from xut.golden import replay
from xut.hw.compile import HwUnrenderable, compile_program
from xut.hw.image import width
from xut.hw.replay import ModelDut, hw_replay
from xut.paths import repo_root
from xut.runners.base import RunContext
from xut.runners.python import generate
from xut.stimgen import VecBuilder
from xut.testspec import declared, discover, select
from xut.wrap import build_map
from xut_models.base import Out
from xut_models.registry import get


@pytest.mark.parametrize("init", [0, 1])
def test_toy(init):
    m = toy_map(f"init{init}", init)
    b = VecBuilder(m, seed=3)
    b.sample("start")
    for d in (1, 0, 1):
        b.set(D=d)
        b.cycle("C")
    vec = b.build()
    assert hw_replay(ToyDff, vec, m).samples == replay(ToyDff, vec, m)[0].samples


def test_two_state_reports_a_dont_care_as_0():
    """``ModelDut`` keeps a golden ``-`` (``compare`` masks it); ``two_state`` reports it as
    ``0``, as 2-state silicon would, so the emulator never prints a bit the RTL cannot."""

    class DashDff(ToyDff):
        def outputs(self):
            return {"Q": Out("-", "doc:1")}

    m = toy_map("init0", 0)
    t0 = "0" * width(m.nin)
    for two_state, want in ((False, "-"), (True, "0")):
        dut = ModelDut(DashDff, {}, m, two_state=two_state)
        dut.reset(t0)
        assert dut.out_bits() == want


#: The flops unit's own directories: while any exists, the flops cases must be found.
FLOPS_DIRS = ("tests/7series/register/_shared/flops", "tests/7series/register/FD*")
NO_FLOPS = (
    "no flops vector tests in this tree: the flops unit (unit/7series/flops) is not merged "
    "yet (ruling S54); this test runs once it is"
)
LOST_FLOPS = (
    "the flops unit's directories exist ({dirs}) but no flops vector case was discovered: "
    "discovery or selection is broken, so the ruling S54 skip no longer applies"
)


def _flops_dirs(root: Path) -> list[str]:
    return sorted(str(d.relative_to(root)) for g in FLOPS_DIRS for d in root.glob(g) if d.is_dir())


def _flops_vector_cases(root: Path):
    """One param per flops vector case. With none: a skip while the flops unit is absent
    (ruling S54), but a failing param once its directories exist, so the skip cannot
    outlive the ruling."""
    cases = [c for c in select(discover(root), ["unit:flops"]) if c.style == "vector"]
    if cases:
        return [pytest.param(c, id=c.id) for c in cases]
    dirs = _flops_dirs(root)
    if dirs:
        return [pytest.param(LOST_FLOPS.format(dirs=", ".join(dirs)), id="flops-cases-lost")]
    return [pytest.param(None, id="no-flops-tests", marks=pytest.mark.skip(reason=NO_FLOPS))]


def test_s54_skip_only_while_the_flops_unit_is_absent(tmp_path):
    (tmp_path / "tests").mkdir()
    [absent] = _flops_vector_cases(tmp_path)
    assert absent.id == "no-flops-tests" and absent.marks
    for d in FLOPS_DIRS:
        root = tmp_path / d.replace("*", "RE")
        root.mkdir(parents=True)
        [lost] = _flops_vector_cases(tmp_path)
        assert lost.id == "flops-cases-lost" and not lost.marks
        assert d.replace("*", "RE") in lost.values[0]
        root.rmdir()


@pytest.mark.parametrize("case", _flops_vector_cases(repo_root()))
def test_every_renderable_flops_configuration(case):
    """Every renderable flops vector configuration of a case declared hw "yes" (a superset
    of what the hw runner runs: its ``config_exclusions.hw`` are checked too, which is
    stricter): the interpreted harness program reproduces the golden trace exactly, '-'
    bits included. The golden model both packs and unpacks the wrapper's vectors through
    one ``DutMap``, so a wrong map would round-trip here; the simulator runners cover it."""
    if isinstance(case, str):
        pytest.fail(case)
    hw, why = declared(case, "hw")
    if not hw:
        state = case.runners.get("hw")
        pytest.skip(f"hw {state} for {case.id}: {why}" if state else f"hw {why} for {case.id}")
    from xut.modelsrc import resolve

    ctx = RunContext(repo_root(), "rtl", resolve("auto"))
    model = get(case.family, case.prim)
    ran = 0
    for vec, spec in generate(case, ctx):
        m = build_map(spec)
        try:
            compile_program(vec, m)
        except HwUnrenderable:
            continue
        assert hw_replay(model, vec, m).samples == replay(model, vec, m)[0].samples, vec.cfg
        ran += 1
    assert ran, "no renderable configuration: the test proves nothing"
