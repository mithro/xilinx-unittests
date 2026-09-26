# SPDX-License-Identifier: Apache-2.0
"""Shared pytest setup: the ``container`` and ``vivado`` markers skip, with the reason,
when the xut-sim image is not built or Vivado 2025.2 is not installed. One definition
for every test module (review A5), instead of a per-module ``needs_image``. Every
``vivado`` test is also marked ``slow``, so ``-m "not slow"`` is a quick loop.

The suite is ``tmp_path``-hermetic and runs in parallel:
``uv run pytest -n auto --dist loadfile`` (pytest-xdist; ``loadfile`` keeps each module's
process-level caches on one worker).

Git runs as it does in CI: without the user's global or system config, so a global
``core.excludesFile`` (commonly ``*.pyc``) cannot hide an untracked file from
``xut.provenance`` and pass a test locally that fails in CI."""

import os
import shutil
from pathlib import Path

import pytest

#: The repository's own ``.gitignore``: a throwaway checkout that ``xut run`` stamps
#: copies it, so what counts as an untracked (dirty) input is what it is in the repo.
REPO_GITIGNORE = Path(__file__).resolve().parents[2] / ".gitignore"


@pytest.fixture(autouse=True)
def _ci_like_git(monkeypatch):
    """No global or system git config (CI has none) and no default global excludes
    file (``$XDG_CONFIG_HOME/git/ignore``, read even without a global config)."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", os.devnull)


@pytest.fixture
def toy(monkeypatch):
    """TOYFF without a catalog file or a xut_models module: ToyDff is its golden model.
    Shared by the runner test modules (base, iverilog, xsim)."""
    from test_golden import ToyDff
    from test_runner_base import TOY_ENTRY

    monkeypatch.setattr("xut.catalog.model.load_entry", lambda family, name, root: TOY_ENTRY)
    monkeypatch.setattr("xut_models.registry.get", lambda family, prim: ToyDff)


@pytest.fixture
def work(tmp_path):
    """A fresh run root outside the worktree (the iverilog runner mounts it at
    /xut-root), so no test writes into the worktree's build/."""
    return tmp_path


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    from xut.container import SIM_IMAGE, image_digest
    from xut.paths import VIVADO_SRC

    want_image = any(i.get_closest_marker("container") for i in items)
    have_image = (
        want_image and shutil.which("docker") is not None and image_digest(SIM_IMAGE) is not None
    )
    have_vivado = (VIVADO_SRC / "glbl.v").is_file()
    no_image = pytest.mark.skip(reason=f"{SIM_IMAGE} not built (run: uv run xut container build)")
    no_vivado = pytest.mark.skip(reason=f"Vivado 2025.2 not installed ({VIVADO_SRC})")
    for item in items:
        if item.get_closest_marker("vivado"):
            item.add_marker(pytest.mark.slow)  # every Vivado test is slow: -m "not slow"
        if item.get_closest_marker("container") and not have_image:
            item.add_marker(no_image)
        if item.get_closest_marker("vivado") and not have_vivado:
            item.add_marker(no_vivado)
