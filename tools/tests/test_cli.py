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
