# SPDX-License-Identifier: Apache-2.0
"""Per-primitive status (``status/<family>/<PRIM>.yaml``, spec §11).

The status file is the source of truth for a primitive's measured results and
functional-coverage bins. ``xut status generate`` (Task 7) renders it into
`status/PROGRESS.md` and friends; this module only defines the schema, loads
and validates a status file, and builds a fresh stub.
"""

import os
import subprocess
from pathlib import Path

import yaml

from xut import schemas
from xut.catalog.model import CatalogEntry, is_enumerated
from xut.errors import GitError

#: Valid values for a `results` entry (spec §11).
RESULT_VALUES = ("pass", "fail", "error", "skip", "not-run", "unsupported", "n/a")

HEADER = "# SPDX-License-Identifier: Apache-2.0\n"

#: Runner display order for a PROGRESS.md level cell (spec §11 layout, Task 7 brief).
RUNNER_ORDER = ("python", "xsim", "iverilog", "verilator", "hw")

#: Test levels, in column order.
LEVELS = ("L0", "L1", "L2", "L3")

#: Precedence when several flows of one runner disagree (worst/most-informative
#: first), and the source of truth for the PROGRESS.md legend: "fail beats error
#: beats pass" (brief), extended to cover every RESULT_VALUES entry (controller
#: ruling on Task 7 concern 1). A deliberate `skip` (skipped with a reason) and a
#: `not-run` cell (never attempted) mean different things and get distinct marks;
#: `skip` outranks `not-run` because a recorded skip is more informative than no
#: record at all. A runner with no matching `results` entry at all is treated as
#: `not-run`.
_PRECEDENCE = ("fail", "error", "pass", "skip", "not-run", "unsupported", "n/a")

#: Compact one-character marks for a runner's aggregated result at one level, one
#: per `_PRECEDENCE` entry (== one per `RESULT_VALUES` entry: all 7 are distinct).
_MARKS = {
    "fail": "✗",
    "error": "!",
    "pass": "✓",
    "skip": "s",
    "not-run": "–",
    "unsupported": "∅",
    "n/a": "·",
}
_NOT_RUN_MARK = _MARKS["not-run"]

#: The PROGRESS.md legend line: every mark, in `_PRECEDENCE` order, labelled with
#: the `results` value it stands for.
_LEGEND = "Marks: " + ", ".join(f"`{_MARKS[v]}` {v}" for v in _PRECEDENCE) + "."


def validate(data: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` is not a valid status entry."""
    schemas.validate(data, "status")


def load_status(path: Path) -> dict:
    """Load and validate a ``status/<family>/<PRIM>.yaml`` file."""
    data = yaml.safe_load(Path(path).read_text())
    validate(data)
    return data


def coverage_bins(entry: CatalogEntry) -> list[str]:
    """Functional coverage bins for `entry` (spec §9): ``port:<P>`` for every port,
    ``attr:<A>=<v>`` for every allowed enumerated value of an attribute, ``attr:<A>``
    for a non-enumerated or undeclared (``allowed`` is advisory and may be empty)
    attribute, and ``claim:<id>`` for every behavioural claim."""
    bins: list[str] = [f"port:{p['name']}" for p in entry.ports]
    for a in entry.attributes:
        allowed = a.get("allowed") or []
        if is_enumerated(allowed):
            bins.extend(f"attr:{a['name']}={v}" for v in allowed)
        else:
            bins.append(f"attr:{a['name']}")
    bins.extend(f"claim:{c['id']}" for c in entry.claims)
    return bins


def new_stub(entry: CatalogEntry, unit: str) -> dict:
    """A fresh status entry for `entry`, owned by work unit `unit`: no measurements or
    results yet, every coverage bin uncovered."""
    return {
        "primitive": entry.name,
        "family": entry.family,
        "work_unit": unit,
        "model_library": entry.model["library"],
        "measured": {"tree_hash": None, "tools": {}},
        "results": {},
        "findings": [],
        "coverage": {"covered": [], "uncovered": coverage_bins(entry)},
        "notes": "",
    }


def dump_stub(entry: CatalogEntry, unit: str) -> str:
    """Render ``new_stub(entry, unit)`` as deterministic YAML text with the SPDX header."""
    data = new_stub(entry, unit)
    validate(data)
    return HEADER + yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def current_branch() -> str:
    """The current git branch name (``git rev-parse --abbrev-ref HEAD``).

    Honours the ``XUT_BRANCH`` env var as an override, checked first: CI checks out a
    pull_request event's head commit as a **detached HEAD** (a merge ref, not the PR's
    actual branch), so ``git rev-parse --abbrev-ref HEAD`` would return ``"HEAD"``, not
    the branch name ``xut lint --branch``'s branch-ownership rules need. CI sets
    ``XUT_BRANCH: ${{ github.head_ref }}`` for exactly this reason (controller ruling).

    A thin, separately-mockable wrapper so ``xut status generate`` can be tested
    without depending on the actual checked-out branch.

    Raises ``GitError`` (a RuntimeError) with a short, readable message (never a raw
    ``subprocess.CalledProcessError``) if git fails, e.g. outside a checkout —
    the same defensive style ``cli._generated_header`` uses for the same command,
    except here the failure can't be silently defaulted away: the branch decides
    whether ``xut status generate`` is allowed to run at all. The CLI turns this
    into a clean, non-traceback ``click.ClickException``.
    """
    override = os.environ.get("XUT_BRANCH")
    if override:
        return override

    from xut.paths import repo_root

    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(
            "current_branch(): `git rev-parse --abbrev-ref HEAD` failed: "
            + (proc.stderr.strip() or f"exit code {proc.returncode}")
        )
    return proc.stdout.strip()


def _runner_mark(results: dict, level: str, runner: str) -> str:
    """The single mark for `runner` at `level`, aggregated over every flow.

    ``–`` (not-run) if `results` has no ``<level>/<runner>/<flow>`` entry at all;
    otherwise the mark for whichever value present has the highest `_PRECEDENCE`.
    """
    prefix = f"{level}/{runner}/"
    values = {v for k, v in results.items() if k.startswith(prefix)}
    if not values:
        return _NOT_RUN_MARK
    for value in _PRECEDENCE:
        if value in values:
            return _MARKS[value]
    return _NOT_RUN_MARK  # defensive: an unrecognised value never validates


def _level_cell(results: dict, level: str) -> str:
    """The compact runner-mark string for one level cell (spec §11, Task 7 brief)."""
    return "".join(_runner_mark(results, level, runner) for runner in RUNNER_ORDER)


def _coverage_pct(coverage: dict) -> str:
    covered = len(coverage["covered"])
    total = covered + len(coverage["uncovered"])
    if total == 0:
        return "n/a"
    return f"{round(covered / total * 100)}%"


def _has_pass(status: dict, level: str) -> bool:
    prefix = level + "/"
    return any(v == "pass" for k, v in status["results"].items() if k.startswith(prefix))


def _unit_of_map(units: dict) -> dict[str, str]:
    """primitive -> owning work-unit name, from `xut.workunits.load_units`'s result.

    Shared by `render_progress` and `render_todo` so the two never disagree on
    which unit owns a primitive.
    """
    return {p: name for name, u in units.items() for p in u.primitives}


def _primitive_table_row(status: dict, unit: str) -> str:
    prim = status["primitive"]
    cells = " | ".join(_level_cell(status["results"], level) for level in LEVELS)
    return (
        f"| {prim} | {unit} | {status['model_library']} | {cells} | "
        f"{_coverage_pct(status['coverage'])} | {len(status['coverage']['uncovered'])} | "
        f"{len(status['findings'])} |"
    )


_PRIMITIVE_TABLE_HEADER = (
    "| Primitive | Unit | Model | L0 | L1 | L2 | L3 | Coverage | Uncovered | Findings |"
)
_PRIMITIVE_TABLE_RULE = "|---|---|---|---|---|---|---|---|---|---|"


def render_progress(statuses: list[dict], units: dict) -> str:
    """Render PROGRESS.md: a per-group summary table, then one per-primitive table
    per UG953 group (spec §11; Task 7 brief, review round 1). `units` is
    `xut.workunits.load_units`'s result."""
    unit_of = _unit_of_map(units)
    group_of = {p: u.group_dirs[0] for u in units.values() for p in u.primitives}

    by_group: dict[str, list[dict]] = {}
    for s in statuses:
        # A status whose primitive isn't in `units` (stale/renamed entry, or a
        # unit map the caller hasn't updated yet) has no known UG953 group:
        # bucket it under "?" rather than raising, so one bad status entry
        # doesn't take down the whole report.
        by_group.setdefault(group_of.get(s["primitive"], "?"), []).append(s)

    lines = ["# Progress", "", _LEGEND, "", "## Summary", ""]
    lines.append("| Group | Primitives | L0 pass | L1 pass | L2 pass | L3 pass |")
    lines.append("|---|---|---|---|---|---|")
    for group in sorted(by_group):
        entries = by_group[group]
        counts = [str(sum(_has_pass(s, level) for s in entries)) for level in LEVELS]
        lines.append(f"| {group} | {len(entries)} | " + " | ".join(counts) + " |")
    lines.append("")

    lines.append("## Primitives")
    lines.append("")
    for group in sorted(by_group):
        lines.append(f"### {group}")
        lines.append("")
        lines.append(_PRIMITIVE_TABLE_HEADER)
        lines.append(_PRIMITIVE_TABLE_RULE)
        rows = sorted(
            by_group[group],
            key=lambda s: (unit_of.get(s["primitive"], s["work_unit"]), s["primitive"]),
        )
        for s in rows:
            lines.append(_primitive_table_row(s, unit_of.get(s["primitive"], s["work_unit"])))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_todo(statuses: list[dict], entries: dict) -> str:
    """Render TODO.md: per unit, per primitive, its uncovered bins, unsupported
    cells (with the primitive's `notes` as the reason, if any) and open findings.
    `entries` is `xut.workunits.load_units`'s result. Primitives with nothing
    outstanding are omitted, as are units with no outstanding primitive."""
    unit_of = _unit_of_map(entries)
    by_unit: dict[str, list[dict]] = {}
    for s in statuses:
        by_unit.setdefault(unit_of.get(s["primitive"], s["work_unit"]), []).append(s)

    lines = ["# TODO", ""]
    for unit in sorted(by_unit):
        unit_lines: list[str] = []
        for s in sorted(by_unit[unit], key=lambda s: s["primitive"]):
            item_lines: list[str] = []
            uncovered = s["coverage"]["uncovered"]
            if uncovered:
                item_lines.append("  - Uncovered bins: " + ", ".join(f"`{b}`" for b in uncovered))
            unsupported = sorted(k for k, v in s["results"].items() if v == "unsupported")
            if unsupported:
                reason = f" — {s['notes']}" if s["notes"] else ""
                item_lines.append(
                    "  - Unsupported: " + ", ".join(f"`{k}`" for k in unsupported) + reason
                )
            if s["findings"]:
                item_lines.append(
                    "  - Open findings: "
                    + ", ".join(f"[{f}](../findings/{f}.md)" for f in s["findings"])
                )
            if item_lines:
                unit_lines.append(f"- **{s['primitive']}**")
                unit_lines.extend(item_lines)
        if unit_lines:
            lines.append(f"## {unit}")
            lines.append("")
            lines.extend(unit_lines)
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_log(log_dir: Path) -> str:
    """Render LOG.md: every `log/*.md`, sorted by filename (its timestamp prefix),
    as a link showing its first heading line (spec §11, Task 7 brief)."""
    lines = ["# Log", ""]
    for f in sorted(Path(log_dir).glob("*.md")):
        entry_lines = f.read_text().splitlines()
        title = entry_lines[0].lstrip("#").strip() if entry_lines else f.stem
        lines.append(f"- [{title}](../log/{f.name})")
    return "\n".join(lines) + "\n"
