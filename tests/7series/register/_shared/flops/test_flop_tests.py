# SPDX-License-Identifier: Apache-2.0
import zlib

import pytest
from flop_recipes import KINDS, generators
from flop_tests import ROOT, render_readme, render_test_yaml
from flop_tests import tests_for as _tests_for  # aliased: pytest would else collect it as a test

PRESENT = [p for p in KINDS if (ROOT / "tests/7series/register" / p / "test.yaml").is_file()]
#: M5: primitives whose test.yaml/README are expected to be committed by now. A
#: primitive falling out of PRESENT (the file deleted or renamed) must fail here, not
#: silently degrade test_committed_files_are_current and friends to an empty
#: parametrize (which pytest reports as passing).
EXPECTED_PRESENT = ("FDRE",)


def test_expected_files_are_present():
    missing = [p for p in EXPECTED_PRESENT if p not in PRESENT]
    assert not missing, f"missing committed test.yaml/README.md for {missing}"


def _prims_with_model() -> list[str]:
    """Every KINDS primitive with a registered golden model (FDRE today; FDSE/FDCE/FDPE
    join automatically once Tasks 25/26 add theirs -- M1)."""
    from xut_models.registry import get

    out = []
    for prim in KINDS:
        try:
            get("7series", prim)
        except LookupError:
            continue
        out.append(prim)
    return out


WITH_MODEL = _prims_with_model()


@pytest.mark.parametrize("prim", WITH_MODEL)
def test_exercises_are_reach_confirmed(prim):
    """M1: every vector test's declared ``exercises`` must be a subset of what its own
    recipe actually reaches through the golden model (ruling S23), checked here by
    replaying the real generator -- not just by an uncommitted one-off script. This is
    exactly the class of bug ruling S33's I1 found (a class bin declared but never
    driven): a later recipe edit that silently stops reaching a declared bin now fails
    here instead of surfacing only as an ``xut status record`` warning."""
    from xut.golden import replay
    from xut.stimgen import GenContext
    from xut.wrap import build_map
    from xut_models.registry import get

    k = KINDS[prim]
    model_cls = get("7series", prim)
    gens = generators(prim)
    for e, _ in _tests_for(k):
        if e["style"] != "vector":
            continue
        gen = gens[e["source"].split(":", 1)[1]]
        # The same deterministic seed `xut run` would use (xut.runners.base.seed_for),
        # so this matches what a real python-runner pass actually reaches.
        ctx = GenContext("7series", prim, zlib.crc32(e["id"].encode()))
        reached: set[str] = set()
        for vec in gen(ctx):
            if vec.expect == "reject":  # no behaviour to model: reach.bins() is empty
                continue
            m = build_map(ctx.specs[vec.cfg])
            _, reach = replay(model_cls, vec, m)
            reached |= reach.bins()
        missing = set(e["exercises"]) - reached
        assert not missing, f"{e['id']}: declared exercises never reached: {sorted(missing)}"


@pytest.mark.parametrize("prim", PRESENT)
def test_committed_files_are_current(prim):
    d = ROOT / "tests/7series/register" / prim
    assert (d / "test.yaml").read_text() == render_test_yaml(KINDS[prim]), "re-run flop_tests.py"
    assert (d / "README.md").read_text() == render_readme(KINDS[prim]), "re-run flop_tests.py"


@pytest.mark.parametrize("prim", PRESENT)
def test_every_generator_exists(prim):
    import yaml

    names = generators(prim)
    for t in yaml.safe_load((ROOT / "tests/7series/register" / prim / "test.yaml").read_text())[
        "tests"
    ]:
        if t["style"] == "vector":
            assert t["source"].split(":", 1)[1] in names


def test_every_test_has_gaps():
    for k in KINDS.values():
        assert all(e["gaps"] for e, _ in _tests_for(k)), k.prim


@pytest.mark.parametrize("prim", PRESENT)
def test_validates_against_step1_schema(prim):
    import json

    import jsonschema
    import yaml

    schema = json.loads((ROOT / "tools/xut/schemas/test.schema.json").read_text())
    doc = yaml.safe_load((ROOT / "tests/7series/register" / prim / "test.yaml").read_text())
    jsonschema.validate(doc, schema)
    for t in doc["tests"]:
        assert set(t["runners"].values()) <= {"yes", "no", "unsupported"}
        need = {r for r, v in t["runners"].items() if v != "yes"}
        assert need == set(t.get("unsupported_reasons", {})), t["id"]
