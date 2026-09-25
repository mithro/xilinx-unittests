# SPDX-License-Identifier: Apache-2.0
"""Tests for `xut lint` (tools/xut/lint.py): branch ownership, SPDX headers, generated
files, documented tests and status-file schema validation (AGENTS.md §3, §5)."""

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from xut.cli import main
from xut.lint import (
    GENERATED_STATUS_FILES,
    LintIssue,
    check_branch_paths,
    check_generated_not_committed,
    check_spdx,
    check_status_files,
    check_tests_documented,
)
from xut.workunits import WorkUnit

FLOPS = WorkUnit(name="flops", family="7series", primitives=("FDRE",), group_dirs=("register",))
LUTS = WorkUnit(name="luts", family="7series", primitives=("LUT6",), group_dirs=("clb",))
UNITS = {"flops": FLOPS, "luts": LUTS}


# --- check_spdx -------------------------------------------------------------


def test_spdx_missing_header_is_error(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import os\n")
    issues = check_spdx(tmp_path, ["bad.py"])
    assert issues == [
        LintIssue(
            "bad.py",
            "spdx",
            "missing 'SPDX-License-Identifier: Apache-2.0' in first 3 lines",
            "error",
        )
    ]


def test_spdx_present_header_is_clean(tmp_path):
    f = tmp_path / "good.py"
    f.write_text("# SPDX-License-Identifier: Apache-2.0\nimport os\n")
    assert check_spdx(tmp_path, ["good.py"]) == []


def test_spdx_header_allowed_within_first_three_lines(tmp_path):
    f = tmp_path / "good.sh"
    f.write_text("#!/bin/bash\n# SPDX-License-Identifier: Apache-2.0\necho hi\n")
    assert check_spdx(tmp_path, ["good.sh"]) == []


def test_spdx_ignores_non_rule_extensions(tmp_path):
    (tmp_path / "notes.md").write_text("no header here\n")
    assert check_spdx(tmp_path, ["notes.md"]) == []


def test_spdx_ignores_json(tmp_path):
    (tmp_path / "data.json").write_text("{}\n")
    assert check_spdx(tmp_path, ["data.json"]) == []


def test_spdx_ignores_third_party(tmp_path):
    d = tmp_path / "third_party"
    d.mkdir()
    (d / "vendor.py").write_text("import os\n")
    assert check_spdx(tmp_path, ["third_party/vendor.py"]) == []


def test_spdx_ignores_extraction_report(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "EXTRACTION_REPORT.md").write_text("no header\n")
    assert check_spdx(tmp_path, ["catalog/EXTRACTION_REPORT.md"]) == []


def test_spdx_checks_tools_hooks_regardless_of_extension(tmp_path):
    d = tmp_path / "tools" / "hooks"
    d.mkdir(parents=True)
    (d / "commit-msg").write_text("#!/bin/sh\necho hi\n")
    issues = check_spdx(tmp_path, ["tools/hooks/commit-msg"])
    assert len(issues) == 1
    assert issues[0].path == "tools/hooks/commit-msg"


# --- check_branch_paths -------------------------------------------------------


def test_unit_branch_touching_infra_file_is_error():
    issues = check_branch_paths("unit/7series/flops", ["tools/xut/cli.py"], UNITS)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].rule == "branch-paths"
    assert issues[0].path == "tools/xut/cli.py"


def test_unit_branch_touching_owned_readme_is_ok():
    issues = check_branch_paths(
        "unit/7series/flops", ["tests/7series/register/FDRE/README.md"], UNITS
    )
    assert issues == []


def test_unit_branch_touching_generated_progress_is_error():
    issues = check_branch_paths("unit/7series/flops", ["status/PROGRESS.md"], UNITS)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_unit_branch_own_log_file_is_ok():
    issues = check_branch_paths(
        "unit/7series/flops", ["log/2026-09-26T1200-unit-7series-flops-notes.md"], UNITS
    )
    assert issues == []


def test_unit_branch_other_units_log_file_is_error():
    issues = check_branch_paths(
        "unit/7series/flops", ["log/2026-09-26T1200-unit-7series-luts-notes.md"], UNITS
    )
    assert len(issues) == 1


def test_unit_branch_touching_other_units_owned_path_is_error():
    issues = check_branch_paths("unit/7series/flops", ["status/7series/LUT6.yaml"], UNITS)
    assert len(issues) == 1


def test_unknown_work_unit_branch_is_error():
    issues = check_branch_paths("unit/7series/nosuchunit", ["status/7series/FDRE.yaml"], UNITS)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_malformed_unit_branch_is_error():
    issues = check_branch_paths("unit/flops", [], UNITS)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_integ_branch_scoped_to_its_own_dir():
    ok = check_branch_paths(
        "integ/clock-domain-crossing",
        ["tests/7series/integration/clock-domain-crossing/test.yaml"],
        UNITS,
    )
    assert ok == []
    bad = check_branch_paths(
        "integ/clock-domain-crossing",
        ["tests/7series/integration/other-design/test.yaml"],
        UNITS,
    )
    assert len(bad) == 1


def test_docs_branch_allows_only_superpowers_subtree():
    ok = check_branch_paths("docs/plan", ["docs/superpowers/plans/foo.md"], UNITS)
    assert ok == []
    bad = check_branch_paths("docs/plan", ["docs/review/correctness.md"], UNITS)
    assert len(bad) == 1
    bad2 = check_branch_paths("docs/plan", ["docs/templates/test.yaml"], UNITS)
    assert len(bad2) == 1


def test_infra_branch_allows_non_unit_owned_paths():
    issues = check_branch_paths("infra/bootstrap", ["tools/xut/cli.py"], UNITS)
    assert issues == []


def test_infra_branch_rejects_unit_owned_test_path():
    issues = check_branch_paths(
        "infra/bootstrap", ["tests/7series/register/FDRE/vectors.py"], UNITS
    )
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_infra_branch_allows_status_stub_despite_unit_ownership():
    """status/<family>/*.yaml is in a unit's owned_paths too, but infra branches
    explicitly may still touch it (controller ruling 13)."""
    issues = check_branch_paths("infra/bootstrap", ["status/7series/FDRE.yaml"], UNITS)
    assert issues == []


def test_infra_branch_allows_catalog_generated_and_templates():
    issues = check_branch_paths(
        "infra/bootstrap",
        ["catalog/7series/FDRE.yaml", "docs/templates/test.yaml", "docs/review/correctness.md"],
        UNITS,
    )
    assert issues == []


def test_main_branch_skips_the_check_entirely():
    issues = check_branch_paths("main", ["status/PROGRESS.md", "tests/anything"], UNITS)
    assert issues == []


def test_unknown_branch_prefix_is_error():
    issues = check_branch_paths("wat/nope", ["some/file.py"], UNITS)
    assert len(issues) == 1
    assert issues[0].severity == "error"


def test_unknown_branch_prefix_with_no_changed_files_still_errors():
    issues = check_branch_paths("wat/nope", [], UNITS)
    assert len(issues) == 1
    assert issues[0].path == "wat/nope"


# --- check_generated_not_committed -------------------------------------------


@pytest.mark.parametrize("f", GENERATED_STATUS_FILES)
def test_generated_file_on_non_main_branch_is_error(f):
    issues = check_generated_not_committed([f], "infra/bootstrap")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].rule == "generated-files"


def test_generated_files_on_main_are_allowed():
    issues = check_generated_not_committed(list(GENERATED_STATUS_FILES), "main")
    assert issues == []


def test_non_generated_file_never_flagged():
    issues = check_generated_not_committed(["status/7series/FDRE.yaml"], "infra/bootstrap")
    assert issues == []


# --- check_tests_documented ---------------------------------------------------


def _write_test_yaml(
    dir_: Path, ids: list[str], related: dict | None = None, primitive: str = "FDRE"
) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    tests = []
    for tid in ids:
        entry = {
            "id": tid,
            "level": "L1",
            "style": "vector",
            "exercises": [],
            "attr_sampling": {},
            "runners": {},
            "flows": [],
        }
        if related and tid in related:
            entry["related"] = related[tid]
        tests.append(entry)
    data = {
        "primitive": primitive,
        "family": "7series",
        "work_unit": "flops",
        "doc_refs": [],
        "tests": tests,
    }
    import yaml

    (dir_ / "test.yaml").write_text(yaml.safe_dump(data))


def test_tests_documented_all_ids_present_is_clean(tmp_path):
    d = tmp_path / "tests" / "7series" / "register" / "FDRE"
    _write_test_yaml(d, ["7series.FDRE.L1.reset"])
    (d / "README.md").write_text("Covers `7series.FDRE.L1.reset`.\n")
    assert check_tests_documented(tmp_path) == []


def test_tests_documented_missing_id_is_error(tmp_path):
    d = tmp_path / "tests" / "7series" / "register" / "FDRE"
    _write_test_yaml(d, ["7series.FDRE.L1.reset"])
    (d / "README.md").write_text("Nothing relevant here.\n")
    issues = check_tests_documented(tmp_path)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].rule == "tests-documented"


def test_tests_documented_missing_readme_is_error(tmp_path):
    d = tmp_path / "tests" / "7series" / "register" / "FDRE"
    _write_test_yaml(d, ["7series.FDRE.L1.reset"])
    issues = check_tests_documented(tmp_path)
    assert any("README" in i.message for i in issues)
    assert all(i.severity == "error" for i in issues)


def test_tests_documented_dangling_related_id_is_warning_only(tmp_path):
    d = tmp_path / "tests" / "7series" / "register" / "FDRE"
    _write_test_yaml(
        d,
        ["7series.FDRE.L1.reset"],
        related={"7series.FDRE.L1.reset": ["7series.FDRE.L1.nosuchtest"]},
    )
    (d / "README.md").write_text("Covers `7series.FDRE.L1.reset`.\n")
    issues = check_tests_documented(tmp_path)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].rule == "tests-documented"


def test_tests_documented_existing_related_id_is_clean(tmp_path):
    d = tmp_path / "tests" / "7series" / "register" / "FDRE"
    _write_test_yaml(
        d,
        ["7series.FDRE.L1.reset", "7series.FDRE.L1.set"],
        related={"7series.FDRE.L1.reset": ["7series.FDRE.L1.set"]},
    )
    (d / "README.md").write_text("Covers `7series.FDRE.L1.reset` and `7series.FDRE.L1.set`.\n")
    assert check_tests_documented(tmp_path) == []


def test_tests_documented_related_id_resolves_across_whole_tree(tmp_path):
    """Controller ruling: `related:` ids resolve across ALL tests/**/test.yaml, not just
    the same file — pinned with two fixture test.yaml files in different primitive
    directories."""
    fdre_dir = tmp_path / "tests" / "7series" / "register" / "FDRE"
    fdce_dir = tmp_path / "tests" / "7series" / "register" / "FDCE"
    _write_test_yaml(
        fdre_dir,
        ["7series.FDRE.L1.reset"],
        related={"7series.FDRE.L1.reset": ["7series.FDCE.L1.reset"]},
        primitive="FDRE",
    )
    (fdre_dir / "README.md").write_text("Covers `7series.FDRE.L1.reset`.\n")
    _write_test_yaml(fdce_dir, ["7series.FDCE.L1.reset"], primitive="FDCE")
    (fdce_dir / "README.md").write_text("Covers `7series.FDCE.L1.reset`.\n")

    # The related id lives only in the *other* file's test.yaml: whole-tree resolution
    # must find it there and report nothing.
    assert check_tests_documented(tmp_path) == []


def test_tests_documented_related_id_missing_from_whole_tree_is_warning(tmp_path):
    fdre_dir = tmp_path / "tests" / "7series" / "register" / "FDRE"
    fdce_dir = tmp_path / "tests" / "7series" / "register" / "FDCE"
    _write_test_yaml(
        fdre_dir,
        ["7series.FDRE.L1.reset"],
        related={"7series.FDRE.L1.reset": ["7series.FDCE.L1.nosuchtest"]},
        primitive="FDRE",
    )
    (fdre_dir / "README.md").write_text("Covers `7series.FDRE.L1.reset`.\n")
    _write_test_yaml(fdce_dir, ["7series.FDCE.L1.reset"], primitive="FDCE")
    (fdce_dir / "README.md").write_text("Covers `7series.FDCE.L1.reset`.\n")

    issues = check_tests_documented(tmp_path)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].rule == "tests-documented"
    assert "7series.FDCE.L1.nosuchtest" in issues[0].message


def test_tests_documented_no_test_yaml_anywhere_is_clean(tmp_path):
    (tmp_path / "tests").mkdir()
    assert check_tests_documented(tmp_path) == []


# --- check_status_files --------------------------------------------------------


def test_status_files_valid_entry_is_clean(tmp_path):
    d = tmp_path / "status" / "7series"
    d.mkdir(parents=True)
    (d / "FDRE.yaml").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "primitive: FDRE\n"
        "family: 7series\n"
        "work_unit: flops\n"
        "model_library: unisims\n"
        "measured: {tree_hash: null, tools: {}}\n"
        "results: {}\n"
        "findings: []\n"
        "coverage: {covered: [], uncovered: []}\n"
        "notes: ''\n"
    )
    assert check_status_files(tmp_path) == []


def test_status_files_invalid_entry_is_error(tmp_path):
    d = tmp_path / "status" / "7series"
    d.mkdir(parents=True)
    (d / "FDRE.yaml").write_text(
        "# SPDX-License-Identifier: Apache-2.0\nprimitive: FDRE\nfamily: 7series\n"
    )
    issues = check_status_files(tmp_path)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].rule == "status-schema"


# --- _changed_files / --base ---------------------------------------------------


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo_with_two_commits(tmp_path: Path, base_branch: str) -> None:
    """A tiny local repo: `base_branch` has one commit (a.txt); a `feature` branch
    checked out off it adds a second commit (b.txt). No `origin` remote is configured,
    so `origin/<anything>` never resolves here."""
    _git(["init", "-q", "-b", base_branch], tmp_path)
    _git(["config", "user.email", "t@example.com"], tmp_path)
    _git(["config", "user.name", "T"], tmp_path)
    (tmp_path / "a.txt").write_text("1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "infra: initial"], tmp_path)
    _git(["checkout", "-q", "-b", "feature"], tmp_path)
    (tmp_path / "b.txt").write_text("2\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "infra: add b"], tmp_path)


def test_changed_files_uses_given_base(tmp_path):
    from xut.lint import _changed_files

    _init_repo_with_two_commits(tmp_path, "custombase")
    changed, warning = _changed_files(tmp_path, base="custombase")
    assert changed == ["b.txt"]
    assert warning is None


def test_changed_files_falls_back_when_base_ref_missing(tmp_path):
    from xut.lint import _changed_files

    _init_repo_with_two_commits(tmp_path, "custombase")
    # "origin/custombase" doesn't exist (no origin remote at all); falls back to the
    # bare "custombase", which does.
    changed, warning = _changed_files(tmp_path, base="origin/custombase")
    assert changed == ["b.txt"]
    assert warning == "origin/custombase not found locally; diffing against custombase instead"


def test_lint_passes_base_through_to_changed_files(monkeypatch):
    from xut import lint as lint_mod
    from xut.paths import repo_root

    captured = {}

    def fake_changed_files(root, base="origin/main"):
        captured["base"] = base
        return [], None

    monkeypatch.setattr(lint_mod, "_changed_files", fake_changed_files)
    monkeypatch.setattr("xut.status.current_branch", lambda: "infra/bootstrap")
    lint_mod.lint(repo_root(), True, base="origin/develop")
    assert captured["base"] == "origin/develop"


# --- CLI wiring / end-to-end ---------------------------------------------------


def test_lint_cli_base_option_is_registered():
    result = CliRunner().invoke(main, ["lint", "--help"])
    assert "--base" in result.output


def test_lint_cli_runs_without_branch_flag():
    result = CliRunner().invoke(main, ["lint"])
    assert "issue(s):" in result.output
    assert result.exit_code == 0, result.output


def test_lint_cli_branch_flag_runs_on_this_repo():
    result = CliRunner().invoke(main, ["lint", "--branch"])
    assert "issue(s):" in result.output


def test_lint_cli_exit_code_nonzero_on_error(tmp_path, monkeypatch):
    """A repo-root with a header-less tracked .py file must fail `xut lint`."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "xilinx-unittests"\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "work-units.yaml").write_text("family: 7series\nunits: {}\n")
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    result = CliRunner().invoke(main, ["lint"])
    assert result.exit_code == 1, result.output
    assert "error spdx bad.py" in result.output
