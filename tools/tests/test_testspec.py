# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest
import yaml

from xut.errors import ConfigError
from xut.testspec import declared, discover, select

FIX = Path(__file__).parent / "fixtures"


def test_discover_and_select():
    cases = discover(FIX)
    assert [c.id for c in cases] == ["7series.TOYFF.L1.capture"]
    c = cases[0]
    assert (c.prim, c.level, c.style, c.group) == ("TOYFF", "L1", "vector", "register")
    assert c.source == "vectors/gen.py:l1_capture"  # kept as written in test.yaml
    assert select(cases, ["7series.TOYFF.*"]) == cases
    assert select(cases, ["TOYFF"]) == cases
    assert select(cases, ["FDRE"]) == []


def test_declared():
    c = discover(FIX)[0]
    assert declared(c, "iverilog") == (True, "")
    assert declared(c, "hw") == (False, "toy")
    assert declared(c, "iverilog-vz") == (True, "")  # follows verilator


def _tree(tmp_path: Path, tests: list[dict], prim: str = "FDRE", unit: str = "flops") -> Path:
    d = tmp_path / "tests" / "7series" / "register" / prim
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "primitive": prim,
        "family": "7series",
        "work_unit": unit,
        "doc_refs": [],
        "tests": tests,
    }
    (d / "test.yaml").write_text(yaml.safe_dump(doc))
    return d


def _entry(tid: str, **extra) -> dict:
    e = {
        "id": tid,
        "level": tid.split(".")[2],
        "style": "vector",
        "exercises": [],
        "attr_sampling": {},
        "runners": {"python": "yes"},
        "flows": ["rtl"],
    }
    e.update(extra)
    return e


def test_declared_no_and_undeclared(tmp_path):
    _tree(
        tmp_path,
        [
            _entry(
                "7series.FDRE.L1.a",
                runners={"python": "no", "verilator": "unsupported"},
                unsupported_reasons={"python": "self-checking", "verilator": "x inputs"},
            )
        ],
    )
    c = discover(tmp_path)[0]
    assert declared(c, "python") == (False, "self-checking")
    assert declared(c, "iverilog-vz") == (False, "x inputs")  # follows verilator
    assert declared(c, "xsim") == (False, "not declared")


def test_case_fields_and_defaults(tmp_path):
    d = _tree(
        tmp_path,
        [
            _entry("7series.FDRE.L1.a", config_exclusions={"hw": {"*_d1_*": "r"}}, timeout_s=7),
            _entry(
                "7series.FDRE.L2.b",
                style="sv",
                source="sv/tb_b.sv",
                configs=[{"cfg": "init1", "attrs": {"INIT": "1'b1"}}],
            ),
        ],
    )
    a, b = discover(tmp_path)
    assert a.test_dir == d and a.family == "7series" and a.work_unit == "flops"
    assert a.config_exclusions == {"hw": {"*_d1_*": "r"}}
    assert a.timeout_s == 7 and b.timeout_s is None
    assert a.source is None and b.source == "sv/tb_b.sv"
    assert b.configs == [{"cfg": "init1", "attrs": {"INIT": "1'b1"}}]
    assert a.configs == [] and a.expected_divergence == [] and a.sv_deviations == []
    assert a.shared_dirs == []


def test_select_unit_and_globs(tmp_path):
    _tree(tmp_path, [_entry("7series.FDRE.L1.a"), _entry("7series.FDRE.L2.b")])
    _tree(tmp_path, [_entry("7series.LUT1.L1.c")], prim="LUT1", unit="luts")
    cases = discover(tmp_path)
    ids = lambda cs: [c.id for c in cs]  # noqa: E731
    assert ids(cases) == ["7series.FDRE.L1.a", "7series.FDRE.L2.b", "7series.LUT1.L1.c"]
    assert ids(select(cases, ["unit:luts"])) == ["7series.LUT1.L1.c"]
    assert ids(select(cases, ["*.L2.*", "LUT1"])) == ["7series.FDRE.L2.b", "7series.LUT1.L1.c"]
    assert ids(select(cases, ["7series.FDRE.L1.a"])) == ["7series.FDRE.L1.a"]


def test_discover_invalid_yaml_is_config_error(tmp_path):
    _tree(tmp_path, [_entry("7series.FDRE.L1.a", runners={"python": True})])
    with pytest.raises(ConfigError, match="test.yaml"):
        discover(tmp_path)


def test_discover_duplicate_id_is_config_error(tmp_path):
    _tree(tmp_path, [_entry("7series.FDRE.L1.a"), _entry("7series.FDRE.L1.a")])
    with pytest.raises(ConfigError, match="7series.FDRE.L1.a"):
        discover(tmp_path)


def test_discover_no_tests_dir_is_empty(tmp_path):
    assert discover(tmp_path) == []


def test_exclusions_for_iverilog_vz_follows_verilator(tmp_path):
    from xut.testspec import exclusions_for

    _tree(
        tmp_path,
        [
            _entry(
                "7series.FDRE.L1.a",
                runners={"python": "yes", "verilator": "yes"},
                config_exclusions={"verilator": {"*_x": "x inputs"}, "hw": {"*": "no"}},
            )
        ],
    )
    c = discover(tmp_path)[0]
    assert exclusions_for(c, "iverilog-vz") == {"*_x": "x inputs"}
    assert exclusions_for(c, "hw") == {"*": "no"}
    assert exclusions_for(c, "xsim") == {}
