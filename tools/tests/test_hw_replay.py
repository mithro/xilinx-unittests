# SPDX-License-Identifier: Apache-2.0
"""The harness rendering of a stimulus, interpreted against the golden model, gives the
golden trace: the compiler and the interpreter preserve every behaviour the stepped
harness claims to preserve (spec §5.1 ruling S8')."""

import pytest
from hw_toy import ToyDff, toy_map

from xut.golden import replay
from xut.hw.compile import HwUnrenderable, compile_program
from xut.hw.replay import hw_replay
from xut.paths import repo_root
from xut.runners.base import RunContext
from xut.runners.python import generate
from xut.stimgen import VecBuilder
from xut.testspec import declared, discover, select
from xut.wrap import build_map
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


NO_FLOPS = (
    "no flops vector tests in this tree: the flops unit (unit/7series/flops) is not merged "
    "yet (ruling S54); this test runs once it is"
)


def _flops_vector_cases():
    root = repo_root()
    cases = [c for c in select(discover(root), ["unit:flops"]) if c.style == "vector"]
    if cases:
        return [pytest.param(c, id=c.id) for c in cases]
    return [pytest.param(None, id="no-flops-tests", marks=pytest.mark.skip(reason=NO_FLOPS))]


@pytest.mark.parametrize("case", _flops_vector_cases())
def test_every_renderable_flops_configuration(case, tmp_path):
    """Every flops vector configuration the hw runner would run (declared hw "yes"): the
    interpreted harness program reproduces the golden trace exactly, '-' bits included."""
    if not declared(case, "hw")[0]:
        pytest.skip(f"hw not declared for {case.id}")
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
