# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import jsonschema
import pytest
import yaml

from xut.catalog.model import CatalogEntry, load_entry
from xut.paths import repo_root
from xut.schemas import load_schema
from xut.status import (
    RESULT_VALUES,
    coverage_bins,
    dump_stub,
    load_status,
    new_stub,
    validate,
)
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


#: TEMPORARY: primitive -> the attribute whose catalog values were regenerated on this
#: branch; drop with ``pre_s19`` after the orchestrator's `status init --refresh-bins`.
REGENERATED_ON_BRANCH = {"ICAPE2": "DEVICE_ID"}


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
        if data["measured"]["tree_hash"] is not None:
            continue  # recorded: its coverage is `xut status record`'s
        assert data["coverage"]["covered"] == []
        # `entry` is `load_entry`'s merge of the generated catalog with that primitive's
        # overrides (crosses, claims, port/attribute corrections): a work unit owns its
        # own stub and is expected to refresh it (`xut status init --refresh-bins`) when
        # its overrides add claims or otherwise change `coverage_bins`, so a refreshed
        # stub's `uncovered` is exactly `new` below.
        new = coverage_bins(entry)
        # TEMPORARY (ruling S20): the committed stubs predate ruling S19's port-class
        # and cross bins, and an infra branch may not modify a status file. Once the
        # orchestrator runs `xut status init --refresh-bins` on main, drop `pre_s19`:
        # every never-recorded stub then has exactly `new`. `claim:` bins are excluded
        # too: a work unit's overrides may add claims (or a cross) before that unit gets
        # around to refreshing its own stub, and an unrefreshed stub never has those.
        pre_s19 = [b for b in new if not b.startswith(("cross:", "claim:")) and b.count(":") == 1]
        got = data["coverage"]["uncovered"]
        # TEMPORARY (PR D fix wave): the catalog of a primitive in REGENERATED_ON_BRANCH
        # was regenerated on this infra branch (ICAPE2: DEVICE_ID had been truncated);
        # its stub is refreshed on main with the same --refresh-bins run. Until then the
        # regenerated attribute's bins are left out of the comparison.
        attr = REGENERATED_ON_BRANCH.get(entry.name)
        if attr is not None:
            got, new, pre_s19 = (
                [b for b in bins if not b.startswith(f"attr:{attr}=")]
                for bins in (got, new, pre_s19)
            )
        assert got in (new, pre_s19), entry.name


def test_every_fresh_stub_has_exactly_the_current_bins():
    """A stub `xut status init` writes today (and one --refresh-bins rewrites) has
    exactly coverage_bins(entry), in order, all uncovered."""
    root = repo_root()
    for f in sorted((root / "catalog/7series").glob("*.yaml")):
        if f.name.endswith(".overrides.yaml"):
            continue
        entry = load_entry("7series", f.stem, root)
        stub = yaml.safe_load(dump_stub(entry, "u"))
        assert stub["coverage"] == {"covered": [], "uncovered": coverage_bins(entry)}


# --- port x class and declared-cross bins (ruling S19) -------------------------------------

FDRE_BINS = [
    "port:Q",
    "port:C",
    "port:C:edge",
    "port:CE",
    "port:CE:0",
    "port:CE:1",
    "port:D",
    "port:D:0",
    "port:D:1",
    "port:R",
    "port:R:0",
    "port:R:1",
    "attr:INIT=1'b0",
    "attr:INIT=1'b1",
    "attr:IS_C_INVERTED=1'b0",
    "attr:IS_C_INVERTED=1'b1",
    "attr:IS_D_INVERTED=1'b0",
    "attr:IS_D_INVERTED=1'b1",
    "attr:IS_R_INVERTED=1'b0",
    "attr:IS_R_INVERTED=1'b1",
]


def _fdre_fixture() -> CatalogEntry:
    """A self-contained snapshot of FDRE's generated catalog shape (no overrides layered
    on): pins ruling S19's bin-list semantics independent of the live catalog/overrides,
    which a work unit is free to extend with claims and port corrections of its own."""
    return CatalogEntry(
        name="FDRE",
        family="7series",
        group="REGISTER",
        subgroup="SDR",
        description="D Flip-Flop with Clock Enable and Synchronous Reset",
        doc={"guide": "UG953", "edition": "2026.1", "page": 375},
        model={"library": "unisims", "file": "FDRE.v"},
        ports=[
            _port("Q", "data", direction="output", doc_function="Data output"),
            _port("C", "clock", doc_function="Clock input."),
            _port("CE", "data", doc_function="Active-High register clock enable."),
            _port("D", "data", doc_function="Data input"),
            _port("R", "data", doc_function="Synchronous reset."),
        ],
        attributes=[
            {
                "name": n,
                "kind": "bits",
                "width": 1,
                "default": "1'b0",
                "allowed": ["1'b0", "1'b1"],
                "doc_type": "BINARY",
            }
            for n in ("INIT", "IS_C_INVERTED", "IS_D_INVERTED", "IS_R_INVERTED")
        ],
    )


def test_fdre_bins_are_the_ruling_s19_set():
    """The fixture FDRE entry (no overrides, no claims): 20 bins. The pilot plan's 21
    (13 + 8 claims) is superseded: with its 8 claims a work unit's FDRE has 28 (see
    ``test_fdre_fixture_with_claims_and_active_high_port_bins`` below)."""
    assert coverage_bins(_fdre_fixture()) == FDRE_BINS


def test_fdre_fixture_with_claims_and_active_high_port_bins():
    """A work unit's overrides may add claims and declare a port's active level (ruling
    S19): claim bins append after the attribute bins, and a declared ``active: high``
    async port gets ``assert``/``release`` bins instead of the undeclared ``rise``/
    ``fall`` pair (``port_class_bins``)."""
    e = _fdre_fixture()
    e.ports = [*e.ports, _port("CLR", "async", active="high", doc_function="Async clear.")]
    e.claims = [
        {
            "id": "FDRE.C1",
            "page": 375,
            "provenance": "doc:375",
            "text": "Q takes D at the active clock edge.",
        },
        {"id": "FDRE.C2", "page": 375, "provenance": "doc:375", "text": "CE Low holds Q."},
    ]
    assert coverage_bins(e) == (
        FDRE_BINS[:12]
        + ["port:CLR", "port:CLR:assert", "port:CLR:release"]
        + FDRE_BINS[12:]
        + ["claim:FDRE.C1", "claim:FDRE.C2"]
    )


def _port(name, cls, width=1, direction="input", **extra):
    return {
        "name": name,
        "direction": direction,
        "width": width,
        "cls": cls,
        "doc_function": "",
        **extra,
    }


def test_port_class_bins_by_class():
    from xut.status import port_class_bins

    assert port_class_bins(_port("D", "data", 3)) == [
        "port:D[0]:0",
        "port:D[0]:1",
        "port:D[1]:0",
        "port:D[1]:1",
        "port:D[2]:0",
        "port:D[2]:1",
    ]
    assert port_class_bins(_port("C", "clock")) == ["port:C:edge"]
    assert port_class_bins(_port("CLR", "async")) == ["port:CLR:rise", "port:CLR:fall"]
    assert port_class_bins(_port("CLR", "async", active="high")) == [
        "port:CLR:assert",
        "port:CLR:release",
    ]
    assert port_class_bins(_port("G", "gate", 2, active="low")) == [
        "port:G[0]:assert",
        "port:G[0]:release",
        "port:G[1]:assert",
        "port:G[1]:release",
    ]
    assert port_class_bins(_port("IO", "inout", 1, "inout")) == [
        "port:IO:drive0",
        "port:IO:drive1",
        "port:IO:release",
    ]
    for p in (
        _port("P", "pad"),
        _port("A", "drp", 7),
        _port("O", "clock_out", 1, "output"),
        _port("Q", "data", 1, "output"),
    ):
        assert port_class_bins(p) == []


def test_cross_bins_are_pairwise_over_enumerated_values():
    e = _fdre()
    e.attributes = [
        {"name": "A", "allowed": ["0", "1"]},
        {"name": "B", "allowed": ['"X"', '"Y"']},
        {"name": "C", "allowed": ["1", "2"]},
        {"name": "R", "allowed": ["1 to 128"]},
    ]
    e.crosses = [["A", "B", "C"], ["A", "R"], ["B", "A"]]
    bins = coverage_bins(e)
    cross = [b for b in bins if b.startswith("cross:")]
    assert cross[:4] == ['cross:A=0,B="X"', 'cross:A=0,B="Y"', 'cross:A=1,B="X"', 'cross:A=1,B="Y"']
    assert "cross:A=0,C=2" in cross and 'cross:B="Y",C=1' in cross
    assert 'cross:B="X",A=0' in cross  # a second declared order is its own cross
    assert len(cross) == 16 and not any("R=" in b for b in cross)  # R is not enumerated
    assert bins.index(cross[0]) > bins.index("attr:R")  # after attributes, before claims
