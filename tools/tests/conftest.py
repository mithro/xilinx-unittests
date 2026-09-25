# SPDX-License-Identifier: Apache-2.0
"""Shared pytest setup: the ``container`` and ``vivado`` markers skip, with the reason,
when the xut-sim image is not built or Vivado 2025.2 is not installed. One definition
for every test module (review A5), instead of a per-module ``needs_image``."""

import shutil

import pytest


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
        if item.get_closest_marker("container") and not have_image:
            item.add_marker(no_image)
        if item.get_closest_marker("vivado") and not have_vivado:
            item.add_marker(no_vivado)
