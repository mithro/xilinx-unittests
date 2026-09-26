# SPDX-License-Identifier: Apache-2.0
"""Per-primitive status (``status/<family>/<PRIM>.yaml``, spec §11).

The status file is the source of truth for a primitive's measured results and
functional-coverage bins. ``xut status generate`` (Task 7) renders it into
`status/PROGRESS.md` and friends; ``xut status record`` (``record``) fills it from
the ``result.json`` files of ``xut run``. This module also defines the schema, loads
and validates a status file, and builds a fresh stub.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from itertools import combinations
from pathlib import Path

import jsonschema
import yaml

from xut import schemas
from xut.catalog.model import CatalogEntry, is_enumerated
from xut.errors import ConfigError, GitError, XutError
from xut.provenance import tree_paths, tree_state
from xut.testspec import TestCase

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
#: Display-only (ruling S21): a runner whose flows mix ``pass`` with ``not-run`` or
#: ``skip`` at one level is shown as partial, not as a plain pass.
_PARTIAL_MARK = "◐"

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
#: The marks are the reference model source's (unisim-2025.2); a suffix flags a cell
#: another source disagrees on.
_SOURCE_LEGEND = (
    f"`{_PARTIAL_MARK}` partial: a pass on some flows, not-run or skip on others (fail "
    "and error still win). Marks are for unisim-2025.2; `+gh` flags a level where "
    "unisim-gh-2020.1 passes what 2025.2 fails (or errors), or the reverse; `~gh` means "
    "the unisim-gh-2020.1 results were recorded at another tree hash (stale, not compared). "
    "Within one level/runner/flow, the primitive's tests aggregate as fail > error > "
    "not-run > pass > skip > unsupported > n/a: a declared test not run is never hidden "
    "by another test's pass."
)


def validate(data: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` is not a valid status entry."""
    schemas.validate(data, "status")


def load_status(path: Path) -> dict:
    """Load and validate a ``status/<family>/<PRIM>.yaml`` file."""
    data = yaml.safe_load(Path(path).read_text())
    validate(data)
    return data


def port_class_bins(port: dict) -> list[str]:
    """The port × class bins of one catalog port (spec §9, ruling S19), for inputs and
    inouts only (they come from the applied stimulus, ``xut.golden.Reach``):

    - ``data``: ``port:<P>:0``/``:1``; a multi-bit port per bit, ``port:<P>[i]:0``/``:1``;
    - ``clock``: ``port:<P>:edge``;
    - ``async``/``gate``: ``port:<P>:assert``/``:release`` when the port's ``active``
      level is declared (catalog override), else ``port:<P>:rise``/``:fall``; per bit
      for a multi-bit port;
    - ``inout``: ``port:<P>:drive0``/``:drive1``/``:release``;
    - ``pad``, ``drp``, ``clock_out`` and outputs: none (``port:<P>`` still applies).
    """
    name, cls, width = port["name"], port["cls"], port["width"]
    if port["direction"] == "output":
        return []
    names = [name] if width == 1 else [f"{name}[{i}]" for i in range(width)]
    if cls == "data" and port["direction"] == "input":
        return [f"port:{n}:{v}" for n in names for v in ("0", "1")]
    if cls == "clock":
        return [f"port:{name}:edge"]
    if cls in ("async", "gate"):
        events = ("assert", "release") if port.get("active") else ("rise", "fall")
        return [f"port:{n}:{e}" for n in names for e in events]
    if cls == "inout":
        return [f"port:{name}:{e}" for e in ("drive0", "drive1", "release")]
    return []


def cross_bins(entry: CatalogEntry) -> list[str]:
    """``cross:<A>=<a>,<B>=<b>`` for every declared cross (catalog override ``crosses``),
    every pair of its attributes and every pair of their enumerated values (spec §4.2:
    crosses are covered pairwise). A non-enumerated attribute contributes nothing
    (``xut lint`` rule ``crosses-enumerated`` refuses it)."""
    allowed = {a["name"]: a.get("allowed") or [] for a in entry.attributes}
    out: list[str] = []
    for cross in entry.crosses:
        for a, b in combinations(cross, 2):
            if not (is_enumerated(allowed.get(a, [])) and is_enumerated(allowed.get(b, []))):
                continue
            out.extend(f"cross:{a}={va},{b}={vb}" for va in allowed[a] for vb in allowed[b])
    return list(dict.fromkeys(out))


def coverage_bins(entry: CatalogEntry) -> list[str]:
    """Functional coverage bins for `entry` (spec §9): ``port:<P>`` for every port (the
    port is exercised at all) followed by its port × class bins (``port_class_bins``),
    ``attr:<A>=<v>`` for every allowed enumerated value of an attribute, ``attr:<A>``
    for a non-enumerated or undeclared (``allowed`` is advisory and may be empty)
    attribute, the declared-cross bins (``cross_bins``), and ``claim:<id>`` for every
    behavioural claim."""
    bins: list[str] = []
    for p in entry.ports:
        bins.append(f"port:{p['name']}")
        bins.extend(port_class_bins(p))
    for a in entry.attributes:
        allowed = a.get("allowed") or []
        if is_enumerated(allowed):
            bins.extend(f"attr:{a['name']}={v}" for v in allowed)
        else:
            bins.append(f"attr:{a['name']}")
    bins.extend(cross_bins(entry))
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


def never_recorded(status: dict) -> bool:
    """True for a stub no ``xut status record`` has touched (no tree hash of any source)."""
    m = status["measured"]
    return m["tree_hash"] is None and not m.get("tree_hash_by_model_source")


def refresh_bins(path: Path, entry: CatalogEntry) -> bool:
    """Rewrite a never-recorded stub's coverage to the current ``coverage_bins(entry)``
    (all uncovered); return True if the file changed. A recorded status file is never
    touched, byte for byte (ruling S20): its coverage is ``xut status record``'s."""
    status = load_status(path)
    if not never_recorded(status):
        return False
    coverage = {"covered": [], "uncovered": coverage_bins(entry)}
    if status["coverage"] == coverage:
        return False
    status["coverage"] = coverage
    validate(status)
    Path(path).write_text(
        HEADER + yaml.safe_dump(status, sort_keys=False, default_flow_style=False)
    )
    return True


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
    if not values & {"fail", "error"} and "pass" in values and values & {"not-run", "skip"}:
        return _PARTIAL_MARK
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


def _source_tag(name: str) -> str:
    """``unisim-gh-2020.1`` -> ``gh``: the suffix marking a cell another source disagrees on."""
    return name.removeprefix("unisim-").split("-")[0]


def _disagrees(a: str | None, b: str | None) -> bool:
    """Pass on one model source, fail or error on the other."""
    bad = ("fail", "error")
    return (a == "pass" and b in bad) or (b == "pass" and a in bad)


def _source_suffix(status: dict, level: str) -> str:
    """``+gh`` (one per disagreeing source) when a non-reference model source disagrees
    in pass/fail with the reference ``results`` for any key of ``level``; ``~gh`` instead
    when that source was recorded at another tree hash than the reference (stale)."""
    ref = status["results"]
    hashes = status["measured"].get("tree_hash_by_model_source", {})
    tags = []
    for name, other in sorted(status.get("results_by_model_source", {}).items()):
        if hashes.get(name) != status["measured"]["tree_hash"]:
            if any(k.startswith(level + "/") for k in other):
                tags.append("~" + _source_tag(name))  # stale: not like-for-like
            continue
        if any(k.startswith(level + "/") and _disagrees(ref.get(k), v) for k, v in other.items()):
            tags.append("+" + _source_tag(name))
    return "".join(tags)


def _primitive_table_row(status: dict, unit: str) -> str:
    prim = status["primitive"]
    cells = " | ".join(
        _level_cell(status["results"], level) + _source_suffix(status, level) for level in LEVELS
    )
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

    lines = ["# Progress", "", _LEGEND, _SOURCE_LEGEND, "", "## Summary", ""]
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


def render_todo(statuses: list[dict], units: dict) -> str:
    """Render TODO.md: per unit, per primitive, its uncovered bins, unsupported
    cells (with the primitive's `notes` as the reason, if any) and open findings.
    `units` is `xut.workunits.load_units`'s result. Primitives with nothing
    outstanding are omitted, as are units with no outstanding primitive."""
    unit_of = _unit_of_map(units)
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


# --- xut status record (spec §9, §11) ---------------------------------------------------

#: The reference model source: its results fill ``results``; every other source fills
#: ``results_by_model_source.<source>`` (review (b) round 2, N2).
REFERENCE_MODEL_SOURCE = "unisim-2025.2"

#: The runners ``record`` writes keys for. ``iverilog-vz`` is not recorded: it only
#: guards the Verilator results and feeds ``transform-bug`` findings.
RECORDED_RUNNERS = ("python", "xsim", "iverilog", "verilator", "hw")

#: The UNISIM simulators: an sv/cocotb test's bins count as covered once it passed on one.
SIMULATORS = ("xsim", "iverilog", "verilator")

#: Worst-first precedence for aggregating one ``<level>/<runner>/<flow>`` key over a
#: primitive's tests (ruling S22). ``not-run`` (a declared test with no evidence)
#: outranks ``pass``: another test's pass never hides an unrun one. A ``skip`` is
#: deliberate and carries its reason, so it ranks below ``pass``.
RECORD_PRECEDENCE = ("fail", "error", "not-run", "pass", "skip", "unsupported", "n/a")

_STATUS_LINE = re.compile(r"^\s*(?:[-*]\s*)?Status:\s*(\S+)", re.IGNORECASE)


class DirtyTreeError(XutError, RuntimeError):
    """``xut status record`` refuses to hash uncommitted inputs."""


class RecordError(XutError, LookupError):
    """``xut status record`` has nothing (valid) to record."""


class StaleResultError(XutError, RuntimeError):
    """A result.json was measured at another tree (or a dirty one) than the current."""


def _warn_stderr(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def flows_for(runner: str, flows: list[str]) -> list[str]:
    """The flows ``runner`` has a result key for, given a test's declared ``flows``:
    the golden model (``python``) only runs ``rtl``; ``hw`` never runs ``rtl`` (its keys
    use the declared netlist flows); a simulator runs ``rtl`` plus every declared flow.
    The same rule as ``xut crosscheck``'s declared runners."""
    if runner == "python":
        return ["rtl"]
    if runner == "hw":
        return [f for f in dict.fromkeys(flows) if f != "rtl"]
    return list(dict.fromkeys(["rtl", *flows]))


def worst_result(values: list[str]) -> str:
    """The aggregate of several ``results`` values, by ``RECORD_PRECEDENCE``."""
    return min(values, key=RECORD_PRECEDENCE.index)


def tree_hash(root: Path, paths: list[str]) -> str:
    """``xut.provenance.tree_state(root, paths).tree_hash``. Raises ``DirtyTreeError``
    naming the files when any of ``paths`` has uncommitted changes (a hash of
    uncommitted inputs would be a lie), and ``GitError`` outside a git checkout."""
    st = tree_state(Path(root), paths)
    if st.tree_hash is None or st.dirty is None:
        raise GitError(f"cannot hash {paths[0]}...: not a git checkout ({root})")
    if st.dirty:
        raise DirtyTreeError(
            "refusing to record: uncommitted changes to files the results depend on "
            "(commit them first): " + "; ".join(st.dirty)
        )
    return st.tree_hash


def open_findings(root: Path, prim: str) -> list[str]:
    """The stems of ``findings/<PRIM>-*.md`` whose ``Status:`` line is ``open``."""
    out = []
    for f in sorted((Path(root) / "findings").glob(f"{prim}-*.md")):
        for line in f.read_text().splitlines():
            m = _STATUS_LINE.match(line)
            if m:
                if m.group(1).lower() == "open":
                    out.append(f.stem)
                break
    return out


def _load_result(
    root: Path, flow: str, runner: str, ms: str, test_id: str, warn: Callable[[str], None]
) -> dict | None:
    """``build/<flow>/<runner>/<ms>/<test_id>/result.json``, validated; ``None`` if absent.
    An unreadable, invalid or misplaced one is an ``error`` result (with a warning)."""
    p = Path(root) / "build" / flow / runner / ms / test_id / "result.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
        schemas.validate(data, "result")
    except (OSError, ValueError, jsonschema.ValidationError) as e:
        warn(f"{p}: unusable result.json, recorded as error: {str(e).splitlines()[0]}")
        return {"status": "error", "reason": "unusable result.json", "tools": {}, "_unusable": 1}
    got = (data["flow"], data["runner"], data["model_source"], data["test_id"])
    if got != (flow, runner, ms, test_id):
        warn(f"{p}: result.json names {got}, not its path; recorded as error")
        return {"status": "error", "reason": "misplaced result.json", "tools": {}, "_unusable": 1}
    return data


def _cell(declared_as: str | None, res: dict | None) -> str:
    """One test's ``results`` value for one (runner, flow) (Task 18 brief)."""
    if declared_as == "unsupported":
        return "unsupported"
    if declared_as == "no":
        return "n/a"
    if res is None:
        return "not-run"  # declared (or undeclared: lint warns) but never run
    if res["status"] != "skip":
        return res["status"]
    reason = res.get("reason") or ""
    if reason.startswith("runner unavailable"):
        return "not-run"
    if reason.startswith("runner ") and " does not run " in reason:
        return "n/a"  # the runner cannot run this style at all
    if reason.startswith("declared unsupported"):
        return "not-run"  # a stale result from before the declaration changed
    return "skip"  # e.g. every configuration excluded, with a reason


def _merge_tools(into: dict[str, set[str]], res: dict) -> None:
    for k, v in (res.get("tools") or {}).items():
        into.setdefault(k, set()).add(str(v))
    c = res.get("container")
    if c:
        into.setdefault("container", set()).add(c.get("digest") or c["image"])


def _lit_int(v: str) -> int | None:
    m = re.fullmatch(r"\s*(?:\d*'([bodh]))?([0-9a-fA-F_]+)\s*", v)
    if not m:
        return None
    base = {"b": 2, "o": 8, "d": 10, "h": 16}[(m.group(1) or "d").lower()]
    try:
        return int(m.group(2).replace("_", ""), base)
    except ValueError:
        return None


def enum_value(value: object, allowed: list[str]) -> str | None:
    """``value`` (a Verilog literal, a string with or without quotes, or an int) as the
    matching ``allowed`` literal, or ``None``."""
    s = str(value)
    for cand in (s, f'"{s}"', s.strip('"')):
        if cand in allowed:
            return cand
    n = _lit_int(s)
    if n is not None:
        return next((a for a in allowed if _lit_int(a) == n), None)
    return None


def _config_attrs(
    root: Path, ms: str, case: TestCase, warn: Callable[[str], None]
) -> list[dict[str, object]]:
    """The explicitly-set attributes of every configuration of ``case`` that ran and
    passed against ``ms``: for a vector test, on the golden model (python, its
    ``cfg-<cfg>/stim.xvec``); for sv/cocotb, on at least one simulator (test.yaml
    ``configs``)."""
    from xut.formats import xvec

    out: list[dict[str, object]] = []
    if case.style == "vector":
        py = _load_result(root, "rtl", "python", ms, case.id, warn)
        d = Path(root) / "build/rtl/python" / ms / case.id
        for c in (py or {}).get("configs", []):
            if c.get("status") != "pass":
                continue
            try:
                out.append(dict(xvec.load(d / f"cfg-{c['cfg']}" / "stim.xvec").attrs))
            except (OSError, xvec.XvecError) as e:
                warn(f"{case.id}: cfg {c['cfg']}: unreadable stim.xvec ({e})")
        return out
    passed: set[str] = set()
    for sim in SIMULATORS:
        for flow in flows_for(sim, case.flows):
            r = _load_result(root, flow, sim, ms, case.id, warn)
            passed |= {c["cfg"] for c in (r or {}).get("configs", []) if c["status"] == "pass"}
    cfgs = case.configs or [{"cfg": "default", "attrs": {}}]
    return [dict(c.get("attrs", {})) for c in cfgs if c["cfg"] in passed]


def _crosses_reached(
    root: Path, ms: str, entry: CatalogEntry, case: TestCase, warn: Callable[[str], None]
) -> set[str]:
    """The ``cross:`` bins the passing configurations of ``case`` realise: attribute
    values are the configuration's, else the catalog default (ruling S19)."""
    allowed = {a["name"]: a.get("allowed") or [] for a in entry.attributes}
    defaults = {a["name"]: a["default"] for a in entry.attributes}
    out: set[str] = set()
    for attrs in _config_attrs(root, ms, case, warn):
        vals = {**defaults, **attrs}
        for cross in entry.crosses:
            for a, b in combinations(cross, 2):
                va, vb = enum_value(vals.get(a), allowed[a]), enum_value(vals.get(b), allowed[b])
                if va is not None and vb is not None:
                    out.add(f"cross:{a}={va},{b}={vb}")
    return out


def _sim_passed(root: Path, ms: str, case: TestCase, warn: Callable[[str], None]) -> bool:
    """True if at least one UNISIM simulator passed ``case`` against ``ms``."""
    return any(
        (r := _load_result(root, flow, sim, ms, case.id, warn)) is not None
        and r["status"] == "pass"
        for sim in SIMULATORS
        for flow in flows_for(sim, case.flows)
    )


def _coverage(
    root: Path, ms: str, entry: CatalogEntry, cases: list[TestCase], warn: Callable[[str], None]
) -> dict:
    """``covered`` = (vector ``exercises`` ∩ the python run's ``bins_reached``) ∪ (sv/cocotb
    ``exercises`` of tests that passed on a simulator); ``uncovered`` = the rest of
    ``coverage_bins(entry)`` (spec §9)."""
    bins = coverage_bins(entry)
    known = set(bins)
    covered: set[str] = set()
    for c in cases:
        for b in c.exercises:
            if b not in known:
                warn(f"{c.id}: exercises {b}, which is not a coverage bin of {c.prim}")
        crosses = {b for b in c.exercises if b.startswith("cross:")}
        if crosses and (c.style != "vector" or _sim_passed(root, ms, c, warn)):
            reached_x = _crosses_reached(root, ms, entry, c, warn)
            covered |= crosses & reached_x
            for b in sorted(crosses - reached_x):
                warn(f"{c.id}: declares {b} but no passing configuration has those values")
        if c.style == "vector":
            py = _load_result(root, "rtl", "python", ms, c.id, warn)
            reached = py.get("bins_reached") if py and py["status"] == "pass" else None
            if reached is None:
                if c.exercises:
                    warn(
                        f"{c.id}: no passing python result with bins_reached ({ms}); its "
                        "exercises stay uncovered"
                    )
                continue
            if not _sim_passed(root, ms, c, warn):
                if c.exercises:
                    warn(
                        f"{c.id}: no simulator passed it ({ms}); its exercises stay "
                        "uncovered (ruling S21: the golden model alone covers nothing)"
                    )
                continue
            for b in c.exercises:
                if b.startswith("cross:"):
                    continue  # from the passing configurations, above
                if b in reached:
                    covered.add(b)
                else:
                    warn(f"{c.id}: declares {b} but the golden model did not reach it")
        else:
            if _sim_passed(root, ms, c, warn):
                covered |= {b for b in c.exercises if not b.startswith("cross:")}
    return {
        "covered": [b for b in bins if b in covered],
        "uncovered": [b for b in bins if b not in covered],
    }


_KEY_ORDER = (
    "primitive",
    "family",
    "work_unit",
    "model_library",
    "measured",
    "results",
    "results_by_model_source",
    "findings",
    "coverage",
    "notes",
)


def _in_schema_order(status: dict) -> dict:
    """``status`` with its keys in the documented order (unknown keys last), so a
    recorded file diffs cleanly against the stub it replaces."""
    rank = {k: i for i, k in enumerate(_KEY_ORDER)}
    return dict(sorted(status.items(), key=lambda kv: rank.get(kv[0], len(rank))))


def record(
    root: Path,
    prim: str,
    family: str | None = None,
    model_source: str = REFERENCE_MODEL_SOURCE,
    warn: Callable[[str], None] | None = None,
) -> dict:
    """Record ``prim``'s results against ``model_source`` into
    ``status/<family>/<PRIM>.yaml``; write it and return it (spec §9, §11; Task 18).

    The reference source fills ``results``, ``coverage``, ``measured.tree_hash`` and
    ``measured.tools``; any other fills only ``results_by_model_source.<source>``. Every
    source sets its own ``measured.tree_hash_by_model_source`` and
    ``measured.tools_by_model_source`` entry (replaced, never merged) and joins
    ``measured.model_sources``; ``findings`` is refreshed. Recording one source never
    touches another's results, hash or tools. Every result.json must carry the current
    tree hash and ``dirty: false`` (``xut run`` stamps them), else ``StaleResultError``.
    ``warn`` gets every warning (default: stderr). ``family`` defaults to
    docs/work-units.yaml's (no module hard-codes the family name)."""
    from xut.catalog.model import load_entry
    from xut.testspec import discover
    from xut.workunits import load_family

    warn = warn or _warn_stderr
    root = Path(root)
    family = family or load_family(root)
    cases = [c for c in discover(root) if c.prim == prim and c.family == family]
    if not cases:
        raise RecordError(f"no tests for {prim} under tests/{family}/")
    unit, group = cases[0].work_unit, cases[0].group
    entry = load_entry(family, prim, root)
    thash = tree_hash(root, tree_paths(family, group, prim, unit))

    cells: dict[str, list[str]] = {}
    tools: dict[str, set[str]] = {}
    found = 0
    stale: list[str] = []
    for c in cases:
        for runner in RECORDED_RUNNERS:
            for flow in flows_for(runner, c.flows):
                res = _load_result(root, flow, runner, model_source, c.id, warn)
                if res is not None:
                    found += 1
                    _merge_tools(tools, res)
                    if "_unusable" not in res and (
                        res.get("tree_hash") != thash or res.get("dirty") is not False
                    ):
                        stale.append(
                            f"{flow}/{runner}/{c.id} (tree_hash {res.get('tree_hash')}, "
                            f"dirty {res.get('dirty')})"
                        )
                key = f"{c.level}/{runner}/{flow}"
                cells.setdefault(key, []).append(_cell(c.runners.get(runner), res))
    if not found:
        raise RecordError(
            f"no result.json for any {prim} test under build/*/*/{model_source}/: "
            f"run `xut run {prim} --model-source {model_source}` first"
        )
    if stale:
        raise StaleResultError(
            f"refusing to record {prim}: {len(stale)} result(s) against {model_source} were "
            f"not measured at the current tree {thash} on a clean tree; re-run `xut run "
            f"{prim} --model-source {model_source}`: "
            + "; ".join(stale[:5])
            + (f"; ... ({len(stale) - 5} more)" if len(stale) > 5 else "")
        )
    results = {k: worst_result(v) for k, v in sorted(cells.items())}

    path = root / "status" / family / f"{prim}.yaml"
    if path.is_file():
        try:
            status = load_status(path)
        except (yaml.YAMLError, jsonschema.ValidationError) as e:
            raise ConfigError(f"{path.relative_to(root)}: {str(e).splitlines()[0]}") from e
    else:
        status = new_stub(entry, unit)
    measured = status["measured"]
    status["work_unit"] = unit
    status["model_library"] = entry.model["library"]
    src_tools = {k: ", ".join(sorted(v)) for k, v in sorted(tools.items())}
    by_hash = {**measured.get("tree_hash_by_model_source", {}), model_source: thash}
    by_tools = {**measured.get("tools_by_model_source", {}), model_source: src_tools}
    measured["tree_hash_by_model_source"] = dict(sorted(by_hash.items()))
    measured["tools_by_model_source"] = dict(sorted(by_tools.items()))
    measured["model_sources"] = sorted({*measured.get("model_sources", []), model_source})
    for other, h in by_hash.items():
        if other != model_source and h != thash:
            warn(f"{prim}: {other} was recorded at tree hash {h}, not {thash}: it is stale")
    if model_source == REFERENCE_MODEL_SOURCE:
        measured["tree_hash"] = thash  # the reference's, as in step 1
        measured["tools"] = src_tools
        status["results"] = results
        status["coverage"] = _coverage(root, model_source, entry, cases, warn)
    else:
        by = status.setdefault("results_by_model_source", {})
        by[model_source] = results
        status["results_by_model_source"] = dict(sorted(by.items()))
    status["findings"] = open_findings(root, prim)
    status = _in_schema_order(status)
    validate(status)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.safe_dump(status, sort_keys=False, default_flow_style=False))
    return status
