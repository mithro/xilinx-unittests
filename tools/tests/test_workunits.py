# SPDX-License-Identifier: Apache-2.0


import pytest
from xut.lint import check_branch_paths
from xut.paths import repo_root
from xut.workunits import branch_slug, load_family, load_units, owned_paths, unit_for_branch


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
    """No two units share a path, and no unit-owned path is writable from infra.

    Regression for the fnmatch trap: `*` matches `.`, so a naive infra pattern
    `catalog/7series/*.yaml` would also match `<PRIM>.overrides.yaml`, which
    `owned_paths` assigns to a unit. Status stubs are the one deliberate exception
    (infra may add them; see test_lint).
    """
    units = load_units(repo_root())
    owner_of: dict[str, str] = {}
    for name, u in units.items():
        for pattern in owned_paths(u):
            concrete = _concrete(pattern)
            if not concrete.startswith("status/"):
                assert check_branch_paths("infra/x", [concrete], units), (
                    f"{concrete!r} (owned by unit {name!r}) is writable from infra"
                )
            if concrete in owner_of:
                assert owner_of[concrete] == name, (
                    f"{concrete!r} owned by both {owner_of[concrete]!r} and {name!r}"
                )
            owner_of[concrete] = name


def test_generated_catalog_files_are_infra_owned():
    """Repo invariant (reads the live checkout on purpose): every generated
    catalog/<family>/<PRIM>.yaml, including the longest name, is infra's, never a
    unit's."""
    root = repo_root()
    units = load_units(root)
    family = load_family(root)
    prims = sorted(
        f.stem
        for f in (root / "catalog" / family).glob("*.yaml")
        if not f.name.endswith(".overrides.yaml")
    )
    paths = [f"catalog/{family}/{p}.yaml" for p in prims]
    assert check_branch_paths("infra/x", paths, units) == []
    assert check_branch_paths("unit/7series/flops", paths[:1], units)


def test_load_family_reads_work_units(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/work-units.yaml").write_text("family: fam9\nunits: {}\n")
    assert load_family(tmp_path) == "fam9"


def test_family_literal_lives_only_in_work_units_yaml():
    """docs/work-units.yaml `family` is the one source of truth: no tools/xut module
    hard-codes the family name."""
    xut_dir = repo_root() / "tools/xut"
    hits = [str(f) for f in sorted(xut_dir.rglob("*.py")) if "7series" in f.read_text()]
    assert hits == []


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
