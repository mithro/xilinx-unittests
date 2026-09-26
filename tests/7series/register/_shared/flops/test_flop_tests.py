# SPDX-License-Identifier: Apache-2.0
import pytest
from flop_recipes import KINDS
from flop_tests import ROOT, render_readme, render_test_yaml

PRESENT = [p for p in KINDS if (ROOT / "tests/7series/register" / p / "test.yaml").is_file()]


@pytest.mark.parametrize("prim", PRESENT)
def test_committed_files_are_current(prim):
    d = ROOT / "tests/7series/register" / prim
    assert (d / "test.yaml").read_text() == render_test_yaml(KINDS[prim]), "re-run flop_tests.py"
    assert (d / "README.md").read_text() == render_readme(KINDS[prim]), "re-run flop_tests.py"


@pytest.mark.parametrize("prim", PRESENT)
def test_every_generator_exists(prim):
    import yaml
    from flop_recipes import generators

    names = generators(prim)
    for t in yaml.safe_load((ROOT / "tests/7series/register" / prim / "test.yaml").read_text())[
        "tests"
    ]:
        if t["style"] == "vector":
            assert t["source"].split(":", 1)[1] in names


def test_every_test_has_gaps():
    for k in KINDS.values():
        from flop_tests import tests_for

        assert all(e["gaps"] for e, _ in tests_for(k)), k.prim


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
