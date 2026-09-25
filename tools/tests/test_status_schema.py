# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from xut.catalog.model import load_entry
from xut.paths import repo_root
from xut.status import RESULT_VALUES, coverage_bins, load_status, new_stub, validate
from xut.workunits import load_units

STATUS_SCHEMA = json.loads(
    (Path(__file__).parents[1] / "xut/schemas/status.schema.json").read_text()
)
TEST_SCHEMA = json.loads((Path(__file__).parents[1] / "xut/schemas/test.schema.json").read_text())
TEMPLATE = Path(__file__).parents[2] / "docs/templates/test.yaml"


def _fdre():
    return load_entry("7series", "FDRE", repo_root())


def test_result_values():
    assert RESULT_VALUES == ("pass", "fail", "error", "skip", "not-run", "unsupported", "n/a")


def test_fdre_stub_validates_against_schema():
    stub = new_stub(_fdre(), "flops")
    validate(stub)  # raises on failure


def test_fdre_stub_uncovered_contains_expected_bins():
    stub = new_stub(_fdre(), "flops")
    assert stub["coverage"]["covered"] == []
    assert "port:R" in stub["coverage"]["uncovered"]
    assert "attr:INIT=1'b1" in stub["coverage"]["uncovered"]


def test_fdre_stub_fields():
    stub = new_stub(_fdre(), "flops")
    assert stub["primitive"] == "FDRE"
    assert stub["family"] == "7series"
    assert stub["work_unit"] == "flops"
    assert stub["model_library"] == "unisims"
    assert stub["measured"] == {"tree_hash": None, "tools": {}}
    assert stub["results"] == {}
    assert stub["findings"] == []
    assert stub["notes"] == ""


def test_coverage_bins_non_enumerated_attrs_collapse_to_one_bin():
    bins = coverage_bins(_fdre())
    # IS_C_INVERTED's allowed value is a range ("1'b0 to 1'b1"), not an enumeration.
    assert bins.count("attr:IS_C_INVERTED") == 1
    assert "attr:IS_C_INVERTED=1'b0" not in bins


def test_results_key_pattern_accepts_valid_key():
    stub = new_stub(_fdre(), "flops")
    stub["results"]["L1/xsim/vivado"] = "pass"
    validate(stub)  # raises on failure


@pytest.mark.parametrize(
    "bad_key", ["L4/xsim/vivado", "L1/XSIM/vivado", "L1/xsim/", "xsim/vivado", "L1-xsim-vivado"]
)
def test_bad_results_key_fails_validation(bad_key):
    stub = new_stub(_fdre(), "flops")
    stub["results"][bad_key] = "pass"
    with pytest.raises(jsonschema.ValidationError):
        validate(stub)


def test_result_value_outside_enum_fails_validation():
    stub = new_stub(_fdre(), "flops")
    stub["results"]["L1/xsim/vivado"] = "flaky"
    with pytest.raises(jsonschema.ValidationError):
        validate(stub)


def test_load_status_round_trips(tmp_path):
    stub = new_stub(_fdre(), "flops")
    p = tmp_path / "FDRE.yaml"
    p.write_text("# SPDX-License-Identifier: Apache-2.0\n" + yaml.safe_dump(stub))
    loaded = load_status(p)
    assert loaded == stub


def test_stub_starts_with_spdx_header():
    from xut.status import dump_stub

    text = dump_stub(_fdre(), "flops")
    assert text.startswith("# SPDX-License-Identifier: Apache-2.0\n")


def test_template_test_yaml_validates_for_fdre():
    text = TEMPLATE.read_text().replace("<PRIM>", "FDRE")
    data = yaml.safe_load(text)
    jsonschema.validate(data, TEST_SCHEMA)


def test_every_status_stub_matches_its_catalog_entry_and_work_unit():
    root = repo_root()
    units = load_units(root)
    unit_of = {p: name for name, u in units.items() for p in u.primitives}
    status_dir = root / "status/7series"
    files = sorted(status_dir.glob("*.yaml"))
    assert len(files) == 103
    for f in files:
        data = load_status(f)
        entry = load_entry("7series", f.stem, root)
        assert data["primitive"] == entry.name
        assert data["work_unit"] == unit_of[entry.name]
        assert set(data["coverage"]["uncovered"]) == set(coverage_bins(entry))
        assert data["coverage"]["covered"] == []
