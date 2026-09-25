# SPDX-License-Identifier: Apache-2.0
from click.testing import CliRunner
from xut import __version__
from xut.cli import main
from xut.paths import repo_root


def test_version_option():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_repo_root_contains_pyproject():
    assert (repo_root() / "pyproject.toml").is_file()


# --- clean errors: known failures never escape as tracebacks (review a) ----------


def _assert_clean_error(result, *needles: str) -> None:
    """A clean CLI error: exit 1 via click's error path (SystemExit, not an uncaught
    exception object), an `Error:` line, and every needle in the output."""
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "Error:" in result.output
    for n in needles:
        assert n in result.output, result.output


def _units_yaml(root, body: str) -> None:
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/work-units.yaml").write_text("family: 7series\nunits:\n" + body)


def test_outside_repo_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["status", "init"])
    _assert_clean_error(result, "not inside xilinx-unittests")


def test_duplicate_primitive_in_work_units_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    _units_yaml(
        tmp_path,
        "  flops: {group: register, primitives: [FDRE]}\n"
        "  more: {group: register, primitives: [FDRE]}\n",
    )
    result = CliRunner().invoke(main, ["status", "init"])
    _assert_clean_error(result, "FDRE", "'flops'", "'more'")


def test_status_init_primitive_in_no_unit_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    _units_yaml(tmp_path, "  flops: {group: register, primitives: [FDRE]}\n")
    cat = tmp_path / "catalog/7series"
    cat.mkdir(parents=True)
    (cat / "LUT6.yaml").write_text("name: LUT6\n")
    result = CliRunner().invoke(main, ["status", "init"])
    _assert_clean_error(result, "LUT6", "docs/work-units.yaml")
    assert not (tmp_path / "status/7series/LUT6.yaml").exists()


def test_status_generate_invalid_status_file_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr("xut.status.current_branch", lambda: "main")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    _units_yaml(tmp_path, "  flops: {group: register, primitives: [FDRE]}\n")
    status_dir = tmp_path / "status/7series"
    status_dir.mkdir(parents=True)
    (status_dir / "FDRE.yaml").write_text("primitive: FDRE\n")
    result = CliRunner().invoke(main, ["status", "generate"])
    _assert_clean_error(result, "status/7series/FDRE.yaml", "required property")
    assert not (tmp_path / "status/PROGRESS.md").exists()
