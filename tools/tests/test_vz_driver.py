# SPDX-License-Identifier: Apache-2.0
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from xut.cli import main
from xut.errors import XutError
from xut.modelsrc import ModelSource
from xut.paths import repo_root
from xut.verilatorize import driver
from xut.verilatorize.driver import Manifest, ModelEntry, catalog_choices, verilatorize, vz_dir

FIX = Path(__file__).parent / "fixtures" / "verilatorize"


@pytest.fixture
def src(tmp_path, monkeypatch):
    """A model source holding a few fixtures (one unsupported, one unchanged), and a
    private vz_dir."""
    uni = tmp_path / "src" / "unisims"
    uni.mkdir(parents=True)
    shutil.copy(FIX / "glbl.v", tmp_path / "src" / "glbl.v")
    for f, model in (
        ("vz_trig.v", "VZTRIG"),
        ("vz_generate.v", "VZGEN"),
        ("vz_bad_select.v", "VZBADSEL"),
    ):
        shutil.copy(FIX / f, uni / f"{model}.v")
    (uni / "PLAIN.v").write_text(
        "// SPDX-License-Identifier: Apache-2.0\nmodule PLAIN (output O, input I);\n"
        "  assign O = I; // deassign in a comment is not a construct\nendmodule\n"
    )
    out = tmp_path / "vz"
    monkeypatch.setattr(driver, "vz_dir", lambda ms: out)
    return ModelSource("test-src", tmp_path / "src"), out


def test_classifies_writes_and_records(src):
    ms, out = src
    lines = []
    man = verilatorize(ms, jobs=2, progress=lines.append)
    st = {m: e.status for m, e in man.models.items()}
    assert st == {
        "VZTRIG": "transformed",
        "VZGEN": "transformed",
        "VZBADSEL": "unsupported",
        "PLAIN": "unchanged",
    }
    assert "select or concatenation" in man.models["VZBADSEL"].reason
    trig = man.models["VZTRIG"]
    assert trig.triggers == ["CLR", "PRE", "glbl.GSR"] and trig.forced == ["q"]
    assert man.models["VZGEN"].generate_configs == [{}, {"IS_C_INVERTED": "1'b1"}]
    assert (out / "VZTRIG.v").read_text().startswith("// SPDX-License-Identifier: Apache-2.0")
    assert not (out / "VZBADSEL.v").exists() and not (out / "PLAIN.v").exists()
    assert lines[0] == "progress: done=0 total=4 elapsed_s=0"
    assert lines[-1].startswith("progress: done=4 total=4 elapsed_s=")
    again = Manifest.load(out / "manifest.json")
    assert again == man and again.model_source == "test-src"


def test_incremental_by_source_sha(src):
    ms, out = src
    verilatorize(ms)
    man = Manifest.load(out / "manifest.json")
    man.models["VZTRIG"].equiv = {"default": "pass"}
    man.save(out / "manifest.json")
    lines = []
    verilatorize(ms, progress=lines.append)
    assert lines == ["progress: done=0 total=0 elapsed_s=0"]  # nothing to redo
    f = ms.unisims / "VZTRIG.v"
    f.write_text(f.read_text().replace("CLR", "CLEAR"))
    lines.clear()
    man = verilatorize(ms, progress=lines.append)
    assert lines[-1].startswith("progress: done=1 total=1 ")
    assert man.models["VZTRIG"].triggers == ["CLEAR", "PRE", "glbl.GSR"]
    assert man.models["VZTRIG"].equiv == {}  # a new transform is not yet equivalence-checked
    (out / "VZGEN.v").unlink()  # a missing copy is redone too
    lines.clear()
    verilatorize(ms, progress=lines.append)
    assert lines[-1].startswith("progress: done=1 total=1 ") and (out / "VZGEN.v").is_file()


def test_version_change_redoes_everything(src, monkeypatch):
    ms, out = src
    verilatorize(ms)
    monkeypatch.setattr(driver, "__version__", "99.0")
    lines = []
    verilatorize(ms, progress=lines.append)
    assert lines[-1].startswith("progress: done=4 total=4 ")


def test_model_selection(src):
    ms, out = src
    man = verilatorize(ms, ["VZTRIG"])
    assert set(man.models) == {"VZTRIG"}
    with pytest.raises(XutError, match="NOPE"):
        verilatorize(ms, ["NOPE"])


def test_manifest_of_another_source_is_refused(src):
    ms, out = src
    out.mkdir(parents=True)
    Manifest("other").save(out / "manifest.json")
    with pytest.raises(XutError, match="belongs to model source other"):
        verilatorize(ms)


def test_manifest_rejects_bad_status(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"model_source": "x", "models": {"A": {"status": "ok"}}}))
    with pytest.raises(XutError, match="bad model status"):
        Manifest.load(p)


def test_vz_dir_is_under_build():
    ms = ModelSource("unisim-2025.2", Path("/nowhere"))
    assert vz_dir(ms) == repo_root() / "build" / "verilatorized" / "unisim-2025.2"


def test_catalog_choices_render_verilog_literals():
    ch = catalog_choices("FDRE")
    assert ch["IS_C_INVERTED"] == ["1'b0", "1'b1"]
    assert catalog_choices("VZTRIG") is None
    iddr = catalog_choices("IDDR")
    assert iddr["DDR_CLK_EDGE"][0] == '"OPPOSITE_EDGE"' and iddr["INIT_Q1"] == ["1'b0", "1'b1"]


def test_model_choices_add_the_source_values(tmp_path, monkeypatch):
    # the catalog allows only "7SERIES", the source branches on "VIRTEX6" too
    f = tmp_path / "VZDEV.v"
    f.write_text("""// SPDX-License-Identifier: Apache-2.0
`timescale 1ps/1ps
module VZDEV (output Q, input C, input D, input R);
  parameter SIM_DEVICE = "7SERIES";
  reg q;
  assign Q = q;
  always @(R) if (R) assign q = 1'b0; else deassign q;
  generate if (SIM_DEVICE == "VIRTEX6") begin : g6
    always @(posedge C) q <= ~D;
  end else begin : g7
    always @(posedge C) q <= D;
  end endgenerate
endmodule
""")
    monkeypatch.setattr(driver, "catalog_choices", lambda m: {"SIM_DEVICE": ['"7SERIES"']})
    assert driver.model_choices(f, "VZDEV") == {"SIM_DEVICE": ['"7SERIES"', '"VIRTEX6"']}
    e = driver.transform_one(f, FIX / "glbl.v", tmp_path)
    assert e.status == "transformed"
    assert e.generate_configs == [{}, {"SIM_DEVICE": '"VIRTEX6"'}]


def test_entry_round_trips():
    e = ModelEntry("transformed", "ab", triggers=["R"], equiv={"default": "pass"})
    assert ModelEntry.from_dict(json.loads(json.dumps(e.__dict__))) == e


def test_cli_summary(src, monkeypatch):
    ms, out = src
    monkeypatch.setattr("xut.modelsrc.resolve", lambda name="auto": ms)
    r = CliRunner().invoke(main, ["verilatorize", "--jobs", "2"])
    assert r.exit_code == 0, r.output
    assert "test-src: 2 transformed, 1 unchanged, 1 unsupported" in r.output
    assert "transformed: VZTRIG: triggers=CLR,PRE,glbl.GSR enablers=- configs=1" in r.output
    assert "unsupported: VZBADSEL: procedural assign/deassign to a select" in r.output
    assert "progress: done=4 total=4" in r.output
    r = CliRunner().invoke(main, ["verilatorize", "NOPE"])
    assert r.exit_code == 1 and "no such model(s)" in r.output
