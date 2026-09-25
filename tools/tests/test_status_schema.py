# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import jsonschema
import pytest
import yaml

from xut.catalog.model import load_entry
from xut.paths import repo_root
from xut.schemas import load_schema
from xut.status import RESULT_VALUES, coverage_bins, load_status, new_stub, validate
from xut.workunits import load_units

STATUS_SCHEMA = load_schema("status")
TEST_SCHEMA = load_schema("test")
TEMPLATE = Path(__file__).parents[2] / "docs/templates/test.yaml"


def _fdre():
    """The live catalog/7series/FDRE.yaml (read from the checkout on purpose)."""
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
    e = _fdre()
    e.attributes = [{"name": "INIT_A", "allowed": ["16'h0000 to 16'hffff"]}]
    bins = coverage_bins(e)
    # a multi-bit range is not an enumeration: one bin for the whole attribute
    assert bins.count("attr:INIT_A") == 1
    assert not any(b.startswith("attr:INIT_A=") for b in bins)


def test_coverage_bins_one_bit_inversion_gets_a_bin_per_polarity():
    """Live FDRE catalog entry: UG953's `1'b0 to 1'b1` is enumerated by the parser."""
    bins = coverage_bins(_fdre())
    assert "attr:IS_C_INVERTED=1'b0" in bins
    assert "attr:IS_C_INVERTED=1'b1" in bins
    assert "attr:IS_C_INVERTED" not in bins


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


def test_template_runner_values_are_quoted_strings_not_yaml_booleans():
    """`runners: {xsim: "yes"}`, never `runners: {xsim: yes}`: PyYAML's YAML-1.1
    resolver parses a bare `yes`/`no` as a boolean, and the schema requires a string."""
    text = TEMPLATE.read_text().replace("<PRIM>", "FDRE")
    data = yaml.safe_load(text)
    for t in data["tests"]:
        for runner, value in t["runners"].items():
            assert isinstance(value, str), (
                f"runners.{runner} loaded as {value!r} ({type(value).__name__}); "
                f'quote it in test.yaml (e.g. {runner}: "yes") so it stays a string'
            )


def test_unquoted_yaml_boolean_runner_value_fails_validation():
    """A bare `yes`/`no` in test.yaml is loaded by PyYAML as the boolean True/False, not
    the string "yes"/"no" the schema requires — this must fail validation, loudly."""
    text = TEMPLATE.read_text().replace("<PRIM>", "FDRE").replace('"yes"', "yes")
    data = yaml.safe_load(text)
    assert data["tests"][0]["runners"]["python"] is True  # sanity: PyYAML coerced it
    with pytest.raises(
        jsonschema.ValidationError, match=r"True is not one of \['yes', 'no', 'unsupported'\]"
    ):
        jsonschema.validate(data, TEST_SCHEMA)


def test_every_status_stub_matches_its_catalog_entry_and_work_unit():
    """Repo invariant (reads the live checkout on purpose): every committed status stub
    matches its catalog entry's coverage bins and its docs/work-units.yaml unit."""
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
