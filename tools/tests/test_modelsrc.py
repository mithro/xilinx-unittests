# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.modelsrc: UNISIM model sources (spec §6.2 "Model identity")."""

from pathlib import Path

import pytest

from xut import modelsrc
from xut.errors import XutError
from xut.modelsrc import ModelSource
from xut.paths import VIVADO_SRC, submodule_src


def _fake_src(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    (d / "unisims").mkdir(parents=True)
    (d / "glbl.v").write_text("module glbl; endmodule\n")
    return d


def test_default_candidates_order():
    assert modelsrc._candidates() == [
        ("unisim-2025.2", VIVADO_SRC),
        ("unisim-gh-2020.1", submodule_src()),
    ]


def test_resolve_auto_prefers_vivado(tmp_path, monkeypatch):
    v, g = _fake_src(tmp_path, "viv"), _fake_src(tmp_path, "gh")
    monkeypatch.setattr(
        modelsrc, "_candidates", lambda: [("unisim-2025.2", v), ("unisim-gh-2020.1", g)]
    )
    assert modelsrc.resolve("auto").name == "unisim-2025.2"
    assert modelsrc.resolve().name == "unisim-2025.2"
    assert modelsrc.resolve("unisim-gh-2020.1").src == g


def test_resolve_falls_back_to_submodule(tmp_path, monkeypatch):
    g = _fake_src(tmp_path, "gh")
    monkeypatch.setattr(
        modelsrc,
        "_candidates",
        lambda: [("unisim-2025.2", tmp_path / "missing"), ("unisim-gh-2020.1", g)],
    )
    assert modelsrc.resolve("auto").name == "unisim-gh-2020.1"
    assert list(modelsrc.model_sources()) == ["unisim-gh-2020.1"]


def test_source_without_glbl_is_not_available(tmp_path, monkeypatch):
    d = tmp_path / "noglbl"
    (d / "unisims").mkdir(parents=True)
    monkeypatch.setattr(modelsrc, "_candidates", lambda: [("unisim-2025.2", d)])
    assert modelsrc.model_sources() == {}


def test_resolve_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(modelsrc, "_candidates", lambda: [])
    with pytest.raises(LookupError, match="no UNISIM model source"):
        modelsrc.resolve("auto")


def test_resolve_unavailable_name_raises_clean_error(tmp_path, monkeypatch):
    g = _fake_src(tmp_path, "gh")
    monkeypatch.setattr(modelsrc, "_candidates", lambda: [("unisim-gh-2020.1", g)])
    with pytest.raises(XutError, match=r"'unisim-2025.2' unavailable.*unisim-gh-2020.1"):
        modelsrc.resolve("unisim-2025.2")


def test_retarget_optional(tmp_path):
    ms = ModelSource("x", _fake_src(tmp_path, "s"))
    assert ms.retarget is None
    assert ms.search == [ms.unisims]
    (ms.src / "retarget").mkdir()
    assert ms.retarget == ms.src / "retarget"
    assert ms.search == [ms.unisims, ms.retarget]
    assert ms.unisims == ms.src / "unisims"
    assert ms.glbl == ms.src / "glbl.v"
