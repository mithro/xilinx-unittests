# SPDX-License-Identifier: Apache-2.0

import pytest
from xut.paths import repo_root
from xut.workunits import load_units, owned_paths, unit_for_branch


def test_every_catalog_primitive_in_exactly_one_unit():
    root = repo_root()
    units = load_units(root)
    listed = [p for u in units.values() for p in u.primitives]
    assert len(listed) == len(set(listed)), "primitive listed twice"
    catalog = {
        f.stem
        for f in (root / "catalog/7series").glob("*.yaml")
        if not f.name.endswith(".overrides.yaml")
    }
    assert set(listed) == catalog


def test_owned_paths_for_flops():
    u = load_units(repo_root())["flops"]
    paths = owned_paths(u)
    assert "tests/7series/register/FDRE/**" in paths
    assert "catalog/7series/FDRE.overrides.yaml" in paths
    assert "models/xut_models/7series/_common/flops.py" in paths
    assert "status/7series/FDRE.yaml" in paths
    assert "findings/FDRE-*.md" in paths
    assert "catalog/7series/FDRE.yaml" not in paths  # generated = infra only


@pytest.mark.parametrize(
    "branch,unit", [("unit/7series/flops", "flops"), ("infra/bootstrap", None), ("main", None)]
)
def test_unit_for_branch(branch, unit):
    assert unit_for_branch(branch) == unit


def test_duplicate_primitive_rejected(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/work-units.yaml").write_text(
        "family: 7series\nunits:\n"
        "  a: {group: x, primitives: [P]}\n  b: {group: x, primitives: [P]}\n"
    )
    with pytest.raises(ValueError, match="P"):
        load_units(tmp_path)
