# SPDX-License-Identifier: Apache-2.0

import fnmatch

import pytest
from xut.paths import repo_root
from xut.workunits import INFRA_PATHS, branch_slug, load_units, owned_paths, unit_for_branch


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


def _concrete(pattern: str) -> str:
    """One representative concrete filename matching glob `pattern`."""
    return pattern.replace("**", "sample.yaml").replace("*", "sample")


def test_ownership_is_exclusive():
    """No path is both a work unit's and infra's, and no two units share a path.

    Regression for the fnmatch trap: `*` matches `.`, so a naive
    `catalog/7series/*.yaml` INFRA_PATHS entry would also match
    `<PRIM>.overrides.yaml`, which `owned_paths` assigns to a unit.
    """
    units = load_units(repo_root())
    owner_of: dict[str, str] = {}
    for name, u in units.items():
        for pattern in owned_paths(u):
            concrete = _concrete(pattern)
            matched_infra = [p for p in INFRA_PATHS if fnmatch.fnmatch(concrete, p)]
            assert not matched_infra, (
                f"{concrete!r} (owned by unit {name!r}) also matches "
                f"INFRA_PATHS pattern(s) {matched_infra!r}"
            )
            if concrete in owner_of:
                assert owner_of[concrete] == name, (
                    f"{concrete!r} owned by both {owner_of[concrete]!r} and {name!r}"
                )
            owner_of[concrete] = name


def test_generated_catalog_files_are_infra_owned():
    root = repo_root()
    assert any(fnmatch.fnmatch("catalog/7series/FDRE.yaml", p) for p in INFRA_PATHS)
    prims = {
        f.stem
        for f in (root / "catalog/7series").glob("*.yaml")
        if not f.name.endswith(".overrides.yaml")
    }
    longest = max(prims, key=len)
    path = f"catalog/7series/{longest}.yaml"
    assert any(fnmatch.fnmatch(path, p) for p in INFRA_PATHS), path


@pytest.mark.parametrize(
    "branch,unit", [("unit/7series/flops", "flops"), ("infra/bootstrap", None), ("main", None)]
)
def test_unit_for_branch(branch, unit):
    assert unit_for_branch(branch) == unit


@pytest.mark.parametrize(
    "branch,slug",
    [
        ("unit/7series/flops", "unit-7series-flops"),
        ("infra/bootstrap", "infra-bootstrap"),
        ("docs/plan", "docs-plan"),
        ("main", "main"),
    ],
)
def test_branch_slug(branch, slug):
    assert branch_slug(branch) == slug


def test_duplicate_primitive_rejected(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/work-units.yaml").write_text(
        "family: 7series\nunits:\n"
        "  a: {group: x, primitives: [P]}\n  b: {group: x, primitives: [P]}\n"
    )
    with pytest.raises(ValueError, match="P"):
        load_units(tmp_path)
