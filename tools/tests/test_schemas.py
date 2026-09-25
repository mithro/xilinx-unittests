# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.schemas: one cached loader + validator for every JSON schema."""

import jsonschema
import pytest

from xut import schemas, status
from xut.catalog import model


def test_load_schema_is_cached():
    a = schemas.load_schema("status")
    assert a is schemas.load_schema("status")
    assert a["type"] == "object"


@pytest.mark.parametrize("name", ["catalog", "status", "test"])
def test_every_schema_loads(name):
    assert "$schema" in schemas.load_schema(name)


def test_unknown_schema_name():
    with pytest.raises(FileNotFoundError):
        schemas.load_schema("nope")


def test_validate_raises_validation_error():
    with pytest.raises(jsonschema.ValidationError):
        schemas.validate({}, "test")


def test_modules_do_not_define_their_own_loader():
    """catalog.model and status delegate to xut.schemas (no private copies)."""
    for mod in (model, status):
        assert not hasattr(mod, "_schema")
        assert not hasattr(mod, "SCHEMA_PATH")


# --- test.schema.json: the Task 8 keys ------------------------------------------------


def _test_doc(**extra) -> dict:
    entry = {
        "id": "7series.FDRE.L1.reset",
        "level": "L1",
        "style": "vector",
        "source": "vectors/gen.py:l1_reset",
        "exercises": [],
        "attr_sampling": {},
        "runners": {"python": "yes", "hw": "unsupported"},
        "unsupported_reasons": {"hw": "free-running clock"},
        "flows": ["rtl"],
    }
    entry.update(extra)
    return {
        "primitive": "FDRE",
        "family": "7series",
        "work_unit": "flops",
        "doc_refs": [],
        "tests": [entry],
    }


def test_test_schema_accepts_task8_keys():
    schemas.validate(
        _test_doc(
            config_exclusions={"hw": {"*_d1_*": "IS_D_INVERTED=1 is not hw-renderable"}},
            configs=[{"cfg": "init0", "attrs": {"INIT": "1'b0", "N": 3}}],
            expected_divergence=[
                {
                    "finding": "findings/FDRE-gsr-order.md",
                    "cls": "sim-divergence",
                    "runners": ["verilator"],
                }
            ],
            timeout_s=1200,
            sv_deviations=["uses $urandom"],
        ),
        "test",
    )


def test_test_schema_bare_yes_runner_still_fails():
    """PyYAML reads a bare `yes` as True: the runner value must stay a quoted string."""
    import yaml

    doc = _test_doc()
    doc["tests"][0]["runners"] = yaml.safe_load("{python: yes}")
    with pytest.raises(jsonschema.ValidationError, match="True"):
        schemas.validate(doc, "test")


@pytest.mark.parametrize(
    "extra",
    [
        {"config_exclusions": {"hw": {"*_d1_*": 1}}},  # a reason must be a string
        {"config_exclusions": {"hw": {"*_d1_*": ""}}},  # ... and not empty
        {"config_exclusions": {"hw": "all"}},  # {runner: {glob: reason}}
        {"unsupported_reasons": {"hw": True}},
        {"configs": [{"attrs": {}}]},  # cfg is required
        {"configs": [{"cfg": "bad name"}]},
        {"expected_divergence": [{"finding": "x.md", "cls": "doc-gap", "runners": []}]},
        {
            "expected_divergence": [
                {"finding": "findings/FDRE-a.md", "cls": "known-divergence", "runners": []}
            ]
        },
        {"timeout_s": 0},
        {"no_such_key": 1},
    ],
)
def test_test_schema_rejects_bad_task8_values(extra):
    with pytest.raises(jsonschema.ValidationError):
        schemas.validate(_test_doc(**extra), "test")


def test_test_yaml_template_validates():
    """docs/templates/test.yaml, placeholders filled in, is a valid test.yaml."""
    import yaml

    from xut.paths import repo_root

    text = (repo_root() / "docs/templates/test.yaml").read_text()
    doc = yaml.safe_load(text.replace("<PRIM>", "FDRE").replace("<prim>", "fdre"))
    schemas.validate(doc, "test")
    assert "config_exclusions" in text
