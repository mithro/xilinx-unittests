# SPDX-License-Identifier: Apache-2.0
"""Hierarchies (ruling S45, Task 15 review C1): a model that needs no rewrite but
instantiates a transformed model is gated like a transformed one; every copy its hierarchy
resolves from vz_dir is current; vz_dir does not depend on run order; the equivalence
check runs the original hierarchy against the vz hierarchy."""

import json
import shutil
import threading
from pathlib import Path

import pytest

from xut.container import SIM_IMAGE, image_digest
from xut.modelsrc import ModelSource
from xut.verilatorize import driver, zcmp
from xut.verilatorize.driver import Manifest, ensure_model, hierarchy, instantiated, vz_dir
from xut.verilatorize.equiv import EquivResult, check_model, config_key

FIX = Path(__file__).parent / "fixtures" / "verilatorize"
_no_image = shutil.which("docker") is None or image_digest(SIM_IMAGE) is None


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for name, value in (("_ENTRIES", {}), ("_TOOLS", {}), ("_CHECKED", set())):
        monkeypatch.setattr(driver, name, value)


def _source(tmp_path: Path) -> ModelSource:
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True)
    shutil.copy(FIX / "glbl.v", tmp_path / "src" / "glbl.v")
    shutil.copy(FIX / "vz_parent.v", uni / "VZPARENT.v")
    shutil.copy(FIX / "vz_child.v", uni / "VZCHILD.v")
    (uni / "PLAIN.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\nmodule PLAIN (output O, input I);\n"
        "  assign O = I;\nendmodule\n"
    )
    return ModelSource("hier-src", tmp_path / "src")


def _fake_check(monkeypatch, status: str = "pass") -> list:
    calls = []
    lock = threading.Lock()
    monkeypatch.setattr(driver, "sim_tools", lambda ms, work: "T1")

    def fake(an, ms, out_dir, attrs=None, *, lib=None, seed=1, force_xsim=False):
        with lock:
            calls.append((an.model, dict(attrs or {}), tuple(an.lib_models), an.rewrites))
        return EquivResult(an.model, status, "why", config=config_key(attrs), oracle="iverilog")

    monkeypatch.setattr("xut.verilatorize.equiv.check_model", fake)
    return calls


def test_instantiated_and_hierarchy(tmp_path):
    ms = _source(tmp_path)
    assert instantiated(ms.unisims / "VZPARENT.v") == ["VZCHILD"]
    assert instantiated(ms.unisims / "VZCHILD.v") == []
    assert hierarchy(ms, ["VZPARENT"]) == ["VZPARENT", "VZCHILD"]


def test_unchanged_parent_over_a_transformed_child_is_gated(tmp_path, monkeypatch):
    ms = _source(tmp_path)
    calls = _fake_check(monkeypatch, "fail")
    e = ensure_model(ms, "VZPARENT", {"INIT": 1}, root=tmp_path, log=lambda _l: None)
    out = vz_dir(ms, tmp_path)
    assert (e.status, e.instantiates, e.depends_on_transformed) == (
        "unchanged",
        ["VZCHILD"],
        ["VZCHILD"],
    )
    assert e.gated and e.effective_rewrites == ["zcmp"]
    # its hierarchy was transformed although only the parent was asked for
    assert (out / "VZCHILD.v").is_file() and not (out / "VZPARENT.v").exists()
    # the check: the original parent over the vz child, with the z-compare stimulus
    assert calls == [("VZPARENT", {"INIT": "1'b1"}, ("VZCHILD",), ("zcmp",))]
    man = Manifest.load(out / "manifest.json").models["VZPARENT"]
    assert man.depends_on_transformed == ["VZCHILD"] and man.equiv == {"INIT=1'b1": "fail"}
    from xut.runners.verilator import blocked

    assert blocked(man, "VZPARENT", "INIT=1'b1").startswith("transform-bug: ")
    assert blocked(man, "VZPARENT", "default").startswith("equivalence check error")


def test_a_stale_child_is_retransformed_and_the_parent_rechecked(tmp_path, monkeypatch):
    ms = _source(tmp_path)
    calls = _fake_check(monkeypatch)
    ensure_model(ms, "VZPARENT", {}, root=tmp_path, log=lambda _l: None)
    out = vz_dir(ms, tmp_path)
    assert "reg q = INIT;" in (out / "VZCHILD.v").read_text()
    child = ms.unisims / "VZCHILD.v"
    child.write_text(child.read_text().replace("reg q = INIT;", "reg q = INIT; // edited"))
    for name, value in (("_ENTRIES", {}), ("_TOOLS", {}), ("_CHECKED", set())):
        monkeypatch.setattr(driver, name, value)  # a new process
    ensure_model(ms, "VZPARENT", {}, root=tmp_path, log=lambda _l: None)
    assert "// edited" in (out / "VZCHILD.v").read_text()  # the copy is current again
    assert [c[0] for c in calls] == ["VZPARENT", "VZPARENT"]  # the parent's verdict reset
    man = Manifest.load(out / "manifest.json").models
    assert man["VZPARENT"].equiv == {"default": "pass"}


def test_a_stale_copy_from_another_tool_is_redone(tmp_path, monkeypatch):
    ms = _source(tmp_path)
    _fake_check(monkeypatch)
    ensure_model(ms, "VZCHILD", {}, root=tmp_path, log=lambda _l: None)
    out = vz_dir(ms, tmp_path)
    (out / "VZCHILD.v").write_text("// a stale copy\n")
    man = Manifest.load(out / "manifest.json")
    man.models["VZCHILD"].tool_sha256 = "an-older-tool"
    man.save(out / "manifest.json")
    for name, value in (("_ENTRIES", {}), ("_TOOLS", {}), ("_CHECKED", set())):
        monkeypatch.setattr(driver, name, value)
    ensure_model(ms, "VZPARENT", {}, root=tmp_path, log=lambda _l: None)
    assert "=== 1'bz" not in (out / "VZCHILD.v").read_text()
    assert "stale" not in (out / "VZCHILD.v").read_text()


def _run(root: Path, ms: ModelSource, order: list[str]) -> dict:
    for m in order:
        ensure_model(ms, m, {}, root=root, log=lambda _l: None)
    out = vz_dir(ms, root)
    man = json.loads((out / "manifest.json").read_text())["models"]
    return {
        "files": {f.name: f.read_bytes() for f in sorted(out.glob("*.v"))},
        "models": {m: {k: v for k, v in e.items()} for m, e in man.items()},
    }


def test_vz_dir_does_not_depend_on_run_order(tmp_path, monkeypatch):
    ms = _source(tmp_path)
    _fake_check(monkeypatch)
    a = _run(tmp_path / "a", ms, ["VZCHILD", "VZPARENT", "PLAIN"])
    for name, value in (("_ENTRIES", {}), ("_TOOLS", {}), ("_CHECKED", set())):
        monkeypatch.setattr(driver, name, value)
    b = _run(tmp_path / "b", ms, ["PLAIN", "VZPARENT", "VZCHILD"])
    assert a == b
    assert list(a["files"]) == ["VZCHILD.v"]
    # the parent alone already brings the child: its hierarchy never depends on others
    for name, value in (("_ENTRIES", {}), ("_TOOLS", {}), ("_CHECKED", set())):
        monkeypatch.setattr(driver, name, value)
    c = _run(tmp_path / "c", ms, ["VZPARENT"])
    assert c["files"] == a["files"]


def test_check_covers_gated_parents(tmp_path, monkeypatch):
    ms = _source(tmp_path)
    calls = _fake_check(monkeypatch)
    out = tmp_path / "vz"
    monkeypatch.setattr(driver, "vz_dir", lambda ms: out)
    man = driver.verilatorize(ms, progress=lambda _l: None, check=True)
    assert sorted(c[0] for c in calls) == ["VZCHILD", "VZPARENT"]
    assert man.models["VZPARENT"].equiv == {"default": "pass"}
    assert man.models["PLAIN"].equiv == {} and not man.models["PLAIN"].gated


@pytest.mark.container
@pytest.mark.skipif(_no_image, reason="xut-sim image not built")
def test_hierarchy_equivalence_passes_and_catches_a_wrong_child(tmp_path, monkeypatch):
    """The real check: the original VZPARENT/VZCHILD on Icarus against the original parent
    over the vz child. A child copy with the wrong constant makes the parent's check fail."""
    ms = _source(tmp_path)
    out = tmp_path / "vz"
    monkeypatch.setattr(driver, "vz_dir", lambda ms: out)
    man = driver.verilatorize(ms, progress=lambda _l: None, check=True)
    assert man.models["VZPARENT"].equiv == {"default": "pass"}, man.models["VZPARENT"]
    doc = json.loads((out / "equiv" / "VZPARENT" / "default" / "result.json").read_text())
    assert doc["vz_models"] == ["VZCHILD"] and doc["oracle"] == "iverilog"
    subject = driver.checked(man, "VZPARENT", driver.model_files(ms))
    monkeypatch.setitem(zcmp._CMP, zcmp._SX.CaseEqualityExpression, ("===", "1'b1"))
    bad = tmp_path / "bad"
    bad.mkdir()
    assert driver.transform_one(ms.unisims / "VZCHILD.v", ms.glbl, bad).status == "transformed"
    r = check_model(subject, ms, bad / "equiv", {}, lib=bad)
    assert r.status == "fail" and r.mismatches, r.reason
