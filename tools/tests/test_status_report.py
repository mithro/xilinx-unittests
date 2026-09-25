# SPDX-License-Identifier: Apache-2.0
"""Tests for `xut status generate` (PROGRESS/TODO/LOG rendering, spec §11)."""

import pytest
from click.testing import CliRunner
from xut import status as status_mod
from xut.cli import main
from xut.status import render_log, render_progress, render_todo
from xut.workunits import WorkUnit


def _unit(name="flops", group="register", primitives=("FDRE", "FDSE")):
    return {name: WorkUnit(name=name, family="7series", primitives=primitives, group_dirs=(group,))}


def _status(
    primitive, work_unit="flops", results=None, covered=None, uncovered=None, findings=None
):
    return {
        "primitive": primitive,
        "family": "7series",
        "work_unit": work_unit,
        "model_library": "unisims",
        "measured": {"tree_hash": None, "tools": {}},
        "results": results or {},
        "findings": findings or [],
        "coverage": {"covered": covered or [], "uncovered": uncovered or []},
        "notes": "",
    }


def test_render_progress_marks_pass_and_fail_and_not_run():
    fdre = _status(
        "FDRE",
        results={"L1/iverilog/rtl": "pass", "L1/hw/vivado": "fail"},
    )
    fdse = _status("FDSE")
    out = render_progress([fdre, fdse], _unit())

    lines = out.splitlines()
    fdre_row = next(line for line in lines if line.startswith("| FDRE "))
    fdse_row = next(line for line in lines if line.startswith("| FDSE "))

    # FDRE's L1 cell (python xsim iverilog verilator hw) has a pass and a fail mark.
    # Columns: '' Primitive Unit Model L0 L1 L2 L3 Coverage Uncovered Findings ''
    l1_cell = fdre_row.split("|")[5]
    assert "✓" in l1_cell
    assert "✗" in l1_cell

    # FDSE has no results at all: every level cell is all not-run marks.
    for cell in fdse_row.split("|")[4:8]:
        assert cell.strip() == "–" * 5


def test_render_progress_legend_lists_all_seven_marks():
    out = render_progress([], _unit(primitives=()))
    legend = next(line for line in out.splitlines() if line.startswith("Marks:"))
    for symbol, label in [
        ("✓", "pass"),
        ("✗", "fail"),
        ("!", "error"),
        ("s", "skip"),
        ("–", "not-run"),
        ("∅", "unsupported"),
        ("·", "n/a"),
    ]:
        assert f"`{symbol}` {label}" in legend


def test_render_progress_skip_mark_is_distinct_from_not_run():
    """A deliberate `skip` (skipped with a reason) and a `not-run` cell (never
    attempted) mean different things and must render distinct marks (controller
    ruling on Task 7 concern 1)."""
    fdre = _status("FDRE", results={"L2/xsim/rtl": "skip"})
    fdse = _status("FDSE")  # no results at all -> not-run
    out = render_progress([fdre, fdse], _unit())

    fdre_row = next(line for line in out.splitlines() if line.startswith("| FDRE "))
    fdse_row = next(line for line in out.splitlines() if line.startswith("| FDSE "))
    l2_cell_fdre = fdre_row.split("|")[6]
    l2_cell_fdse = fdse_row.split("|")[6]

    assert "s" in l2_cell_fdre
    assert l2_cell_fdse.strip() == "–" * 5
    assert "s" not in l2_cell_fdse


def test_render_progress_precedence_order():
    """fail > error > pass > skip > not-run > unsupported > n/a (controller ruling
    on Task 7 concern 1) when several flows of one runner disagree."""
    prim = _status(
        "FDRE",
        results={
            # python: pass vs skip -> pass wins.
            "L0/python/a": "pass",
            "L0/python/b": "skip",
            # xsim: skip vs not-run -> skip wins.
            "L1/xsim/a": "skip",
            "L1/xsim/b": "not-run",
            # iverilog: not-run vs unsupported -> not-run wins.
            "L2/iverilog/a": "not-run",
            "L2/iverilog/b": "unsupported",
            # verilator: unsupported vs n/a -> unsupported wins.
            "L3/verilator/a": "unsupported",
            "L3/verilator/b": "n/a",
            # hw: error vs pass -> error wins (fail > error > pass, unaffected).
            "L0/hw/a": "error",
            "L0/hw/b": "pass",
        },
    )
    out = render_progress([prim], _unit(primitives=("FDRE",)))
    row = next(line for line in out.splitlines() if line.startswith("| FDRE "))
    # Columns: '' Primitive Unit Model L0 L1 L2 L3 Coverage Uncovered Findings ''
    l0, l1, l2, l3 = (row.split("|")[i] for i in (4, 5, 6, 7))
    python_mark, _xsim, _iverilog, _verilator, hw_mark = l0.strip()
    assert python_mark == "✓"  # pass beats skip
    assert hw_mark == "!"  # error beats pass
    assert l1.strip()[1] == "s"  # xsim: skip beats not-run
    assert l2.strip()[2] == "–"  # iverilog: not-run beats unsupported
    assert l3.strip()[3] == "∅"  # verilator: unsupported beats n/a


def test_render_progress_groups_primitive_table_by_ug953_group():
    """Review round 1: the per-primitive table is grouped into one `### <group>`
    subsection per UG953 group (sorted), not one flat alphabetical table."""
    units = {
        "flops": WorkUnit(
            name="flops", family="7series", primitives=("FDRE",), group_dirs=("register",)
        ),
        "bufg": WorkUnit(
            name="bufg", family="7series", primitives=("BUFG",), group_dirs=("clock",)
        ),
    }
    fdre = _status("FDRE", work_unit="flops")
    bufg = _status("BUFG", work_unit="bufg")
    out = render_progress([fdre, bufg], units)

    assert "### clock" in out
    assert "### register" in out
    assert out.index("### clock") < out.index("### register")  # sorted alphabetically

    clock_section = out.split("### clock", 1)[1].split("### register", 1)[0]
    register_section = out.split("### register", 1)[1]
    assert "| BUFG " in clock_section
    assert "| FDRE " not in clock_section
    assert "| FDRE " in register_section
    assert "| BUFG " not in register_section


def test_render_progress_primitive_rows_sorted_by_unit_then_primitive():
    """Within a group's table, rows are sorted by (unit, primitive), not just
    primitive: unit `a_unit` sorts before `z_unit` even though its primitive
    (`ZZZZ`) sorts after `z_unit`'s primitive (`AAAA`)."""
    units = {
        "z_unit": WorkUnit(
            name="z_unit", family="7series", primitives=("AAAA",), group_dirs=("clb",)
        ),
        "a_unit": WorkUnit(
            name="a_unit", family="7series", primitives=("ZZZZ",), group_dirs=("clb",)
        ),
    }
    aaaa = _status("AAAA", work_unit="z_unit")
    zzzz = _status("ZZZZ", work_unit="a_unit")
    out = render_progress([aaaa, zzzz], units)
    section = out.split("### clb", 1)[1]
    assert section.index("| ZZZZ ") < section.index("| AAAA ")


def test_render_progress_unknown_group_falls_back_to_question_mark():
    """A status for a primitive absent from `units` still renders, grouped under
    the `?` placeholder group, instead of raising."""
    out = render_progress([_status("MYSTERY", work_unit="?")], _unit(primitives=()))
    assert "### ?" in out
    assert "| MYSTERY " in out


def test_render_progress_coverage_percentage():
    fdre = _status("FDRE", covered=["port:C", "port:D"], uncovered=[f"port:{i}" for i in range(6)])
    out = render_progress([fdre], _unit(primitives=("FDRE",)))
    assert "25%" in out


def test_render_log_orders_by_filename(tmp_path):
    (tmp_path / "2026-01-01T0000-a-first.md").write_text("# First Entry\n\nbody\n")
    (tmp_path / "2026-02-02T0000-b-second.md").write_text("# Second Entry\n\nbody\n")
    out = render_log(tmp_path)
    assert out.index("First Entry") < out.index("Second Entry")


def test_render_todo_lists_uncovered_bins_unsupported_and_findings():
    fdre = _status(
        "FDRE",
        results={"L1/hw/vivado": "unsupported"},
        uncovered=["port:R"],
        findings=["FDRE-reset-glitch"],
    )
    out = render_todo([fdre], units=_unit(primitives=("FDRE",)))
    assert "port:R" in out
    assert "L1/hw/vivado" in out
    assert "FDRE-reset-glitch" in out


def test_current_branch_raises_clean_runtime_error_on_git_failure(monkeypatch, tmp_path):
    class _FailedProc:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository (or any of the parent directories)\n"

    monkeypatch.delenv("XUT_BRANCH", raising=False)
    monkeypatch.setattr(status_mod.subprocess, "run", lambda *a, **k: _FailedProc())
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    with pytest.raises(RuntimeError, match="not a git repository"):
        status_mod.current_branch()


def test_current_branch_honours_xut_branch_env_override(monkeypatch):
    """CI sets XUT_BRANCH for a pull_request build, whose checkout is a detached HEAD
    (controller ruling); the override must win without even shelling out to git."""

    def _boom(*a, **k):
        raise AssertionError("git should not run when XUT_BRANCH is set")

    monkeypatch.setattr(status_mod.subprocess, "run", _boom)
    monkeypatch.setenv("XUT_BRANCH", "unit/7series/flops")
    assert status_mod.current_branch() == "unit/7series/flops"


def test_current_branch_falls_through_to_git_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XUT_BRANCH", raising=False)

    class _Proc:
        returncode = 0
        stdout = "infra/bootstrap\n"
        stderr = ""

    monkeypatch.setattr(status_mod.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)
    assert status_mod.current_branch() == "infra/bootstrap"


def test_generate_cli_wraps_current_branch_failure_cleanly(monkeypatch):
    """A `current_branch()` failure must surface as a clean, non-traceback CLI
    error, consistent with every other user-facing failure in this command."""

    from xut.errors import GitError

    def _boom():
        raise GitError("current_branch(): git is not installed")

    monkeypatch.setattr("xut.status.current_branch", _boom)
    result = CliRunner().invoke(main, ["status", "generate"])
    assert result.exit_code != 0
    assert "git is not installed" in result.output
    assert "Traceback" not in result.output


def test_generate_refuses_off_main_without_force(monkeypatch):
    monkeypatch.setattr("xut.status.current_branch", lambda: "unit/7series/flops")
    result = CliRunner().invoke(main, ["status", "generate"])
    assert result.exit_code != 0
    assert "main" in result.output


def test_generate_allows_main(monkeypatch, tmp_path):
    monkeypatch.setattr("xut.status.current_branch", lambda: "main")
    monkeypatch.setattr("xut.paths.repo_root", lambda start=None: tmp_path)

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/work-units.yaml").write_text(
        "family: 7series\nunits:\n  flops: {group: register, primitives: [FDRE]}\n"
    )
    status_dir = tmp_path / "status/7series"
    status_dir.mkdir(parents=True)
    (status_dir / "FDRE.yaml").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "primitive: FDRE\nfamily: 7series\nwork_unit: flops\nmodel_library: unisims\n"
        "measured: {tree_hash: null, tools: {}}\nresults: {}\nfindings: []\n"
        "coverage: {covered: [], uncovered: []}\nnotes: ''\n"
    )
    (tmp_path / "log").mkdir()
    (tmp_path / "log/2026-01-01T0000-main-x.md").write_text("# X\n")

    result = CliRunner().invoke(main, ["status", "generate"])
    assert result.exit_code == 0, result.output

    progress = (tmp_path / "status/PROGRESS.md").read_text()
    todo = (tmp_path / "status/TODO.md").read_text()
    log = (tmp_path / "status/LOG.md").read_text()
    for text in (progress, todo, log):
        assert text.startswith("<!-- GENERATED by xut status generate — do not edit -->")
    assert "FDRE" in progress
    assert "X" in log
