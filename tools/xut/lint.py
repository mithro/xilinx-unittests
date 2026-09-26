# SPDX-License-Identifier: Apache-2.0
"""`xut lint`: the checks that let many parallel agents work on separate branches
without interfering (AGENTS.md §3, §5). Enforces branch path ownership, SPDX headers,
never-committed generated files, documented tests, accounted-for coverage bins, stated
gaps and valid status files.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

from xut.errors import GitError, XutError
from xut.schemas import validate as validate_schema
from xut.status import load_status
from xut.testspec import DECLARATION_OF, DECLARED_RUNNERS, finding_id, finding_status
from xut.workunits import WorkUnit, branch_slug, owned_paths, unit_for_branch

#: Tracked-file extensions checked for the SPDX header (global constraints; controller
#: ruling: also `tools/hooks/*` regardless of extension).
_SPDX_EXTENSIONS = {".py", ".v", ".sv", ".yaml", ".yml", ".sh", ".tcl", ".toml"}
#: Never checked even when they'd otherwise match: markdown has no comment syntax, and
#: neither does JSON (controller ruling). `catalog/EXTRACTION_REPORT.md` — excluded by
#: name in the brief — is already covered by the `.md` exclusion here, so it needs no
#: separate exact-path entry.
_SPDX_EXCLUDE_EXTENSIONS = {".md", ".json"}
_SPDX_MARKER = "SPDX-License-Identifier: Apache-2.0"

#: The 4 files `xut status generate` writes (spec §11); AGENTS.md §5 forbids committing
#: them anywhere but `main`.
GENERATED_STATUS_FILES = (
    "status/PROGRESS.md",
    "status/TODO.md",
    "status/LOG.md",
    "status/PORTABILITY.md",
)


@dataclass(frozen=True)
class LintIssue:
    path: str
    rule: str
    message: str
    severity: str  # "error" | "warning"


# --- spdx --------------------------------------------------------------------------


def _spdx_checked(path: str) -> bool:
    if path.startswith("third_party/"):
        return False
    suffix = Path(path).suffix
    if suffix in _SPDX_EXCLUDE_EXTENSIONS:
        return False
    return suffix in _SPDX_EXTENSIONS or path.startswith("tools/hooks/")


def check_spdx(root: Path, files: list[str]) -> list[LintIssue]:
    """Every tracked source file `files` (as returned by `git ls-files`) that matches the
    SPDX rule file set carries the SPDX header in its first 3 lines."""
    root = Path(root)
    issues = []
    for path in files:
        if not _spdx_checked(path):
            continue
        try:
            with (root / path).open(encoding="utf-8", errors="replace") as fh:
                head = [next(fh, "") for _ in range(3)]
        except OSError as e:
            issues.append(LintIssue(path, "spdx", f"could not read file: {e}", "error"))
            continue
        if not any(_SPDX_MARKER in line for line in head):
            issues.append(
                LintIssue(path, "spdx", f"missing '{_SPDX_MARKER}' in first 3 lines", "error")
            )
    return issues


# --- branch-paths ---------------------------------------------------------------------


def _branch_error(branch: str, changed_files: list[str], message: str) -> list[LintIssue]:
    """One issue per changed file, or (if there are none) one issue keyed to the branch
    name itself — a bad branch name is worth flagging even on an empty diff."""
    if not changed_files:
        return [LintIssue(branch, "branch-paths", message, "error")]
    return [LintIssue(f, "branch-paths", message, "error") for f in changed_files]


def _not_owned(changed_files: list[str], allowed: list[str], branch: str) -> list[LintIssue]:
    return [
        LintIssue(f, "branch-paths", f"not owned by branch {branch!r}", "error")
        for f in changed_files
        if not any(fnmatch.fnmatch(f, p) for p in allowed)
    ]


def _infra_allowed_paths(
    changed_files: list[str], units: dict[str, WorkUnit], added: AbstractSet[str]
) -> list[LintIssue]:
    """infra/<topic> may touch anything except a work unit's owned paths (Ruling 12),
    with one exception: it may ADD a new `status/<family>/<PRIM>.yaml` stub even though
    that path is unit-owned (Ruling 24). Modifying or deleting an existing status file
    is the owning unit's job, so it is an error on infra — `added` is the set of paths
    the branch added (`_added_files`), anything else in `changed_files` is a
    modification or deletion."""
    status_patterns = {f"status/{u.family}/*.yaml" for u in units.values()}
    unit_patterns = [(p, u.name) for u in units.values() for p in owned_paths(u)]
    issues = []
    for f in changed_files:
        if any(fnmatch.fnmatch(f, p) for p in status_patterns):
            if f not in added:
                issues.append(
                    LintIssue(
                        f,
                        "branch-paths",
                        "infra may only add status stubs, not modify or delete them "
                        "(the owning work unit does that)",
                        "error",
                    )
                )
            continue
        owner = next((name for p, name in unit_patterns if fnmatch.fnmatch(f, p)), None)
        if owner is not None:
            issues.append(
                LintIssue(f, "branch-paths", f"owned by work unit {owner!r}, not infra", "error")
            )
    return issues


def check_branch_paths(
    branch: str,
    changed_files: list[str],
    units: dict[str, WorkUnit],
    added: AbstractSet[str] = frozenset(),
) -> list[LintIssue]:
    """Every file `branch` touches is within what its branch type owns (AGENTS.md §3,
    controller Rulings 12, 13 and 24). `added` is the subset of `changed_files` the
    branch newly added; only the infra rule needs it. `main` is exempt — nothing but
    `xut status generate` commits there, and every branch-scoping rule below assumes a
    branch cut from `main`."""
    if branch == "main":
        return []

    own_log = f"log/*-{branch_slug(branch)}-*.md"

    if branch.startswith("unit/"):
        unit_name = unit_for_branch(branch)
        if unit_name is None:
            return _branch_error(branch, changed_files, "not a valid unit/<family>/<unit> branch")
        if unit_name not in units:
            return _branch_error(branch, changed_files, f"unknown work unit {unit_name!r}")
        allowed = [*owned_paths(units[unit_name]), own_log]
        return _not_owned(changed_files, allowed, branch)

    if branch.startswith("integ/"):
        rest = branch.removeprefix("integ/")
        if not rest or "/" in rest:
            return _branch_error(branch, changed_files, "not a valid integ/<name> branch")
        families = sorted({u.family for u in units.values()})
        allowed = [*(f"tests/{fam}/integration/{rest}/**" for fam in families), own_log]
        return _not_owned(changed_files, allowed, branch)

    if branch.startswith("docs/"):
        allowed = ["docs/superpowers/**", own_log]
        return _not_owned(changed_files, allowed, branch)

    if branch.startswith("infra/"):
        return _infra_allowed_paths(changed_files, units, added)

    return _branch_error(
        branch, changed_files, "unknown branch prefix (expected unit/, integ/, docs/, infra/)"
    )


# --- generated-files --------------------------------------------------------------


def check_generated_not_committed(changed_files: list[str], branch: str) -> list[LintIssue]:
    """The 4 generated status files (AGENTS.md §5) are written only by `xut status
    generate`, and only on `main`; a work-unit, infra, integ or docs branch must never
    commit them."""
    if branch == "main":
        return []
    return [
        LintIssue(
            f,
            "generated-files",
            "generated file: only `xut status generate` on main may write this",
            "error",
        )
        for f in changed_files
        if f in GENERATED_STATUS_FILES
    ]


# --- tests-documented ---------------------------------------------------------------


def _schema_message(e: jsonschema.ValidationError) -> str:
    """`<json path>: <message>` for one schema failure — enough to find and fix it."""
    return f"{e.json_path}: {e.message}"


def check_tests_documented(root: Path) -> list[LintIssue]:
    """Every `tests/**/test.yaml` validates against `test.schema.json` (rule
    `test-schema`: unparseable YAML, a non-mapping document, a missing `id`, a bare YAML
    `yes`/`no` runner value that PyYAML reads as a boolean — Ruling 14), and every test
    id of a valid file appears (verbatim) in the sibling README.md. A file that fails the
    schema is reported once and skipped for the README checks. A `related:` id that
    doesn't exist anywhere under `tests/**` is a warning, not an error — a stale
    cross-reference is a documentation nit, not a broken build. Every runner declared
    `"no"` or `"unsupported"` must have an `unsupported_reasons` entry (rule
    `runner-reasons`, error): a skip always carries a reason (spec §14). A runner of
    `xut.testspec.DECLARED_RUNNERS` missing from `runners` is a warning
    (`runner-declared`); a runner name outside that list in `runners`,
    `unsupported_reasons` or `config_exclusions` is an error (`runner-unknown`); an
    sv/cocotb exclusion glob matching none of the test's configs is a warning
    (`config-exclusions`; vector configs are only known at run time, where the runner
    logs the same warning). Every `expected_divergence` entry names its finding by the
    exact id `xut crosscheck` gives it (`findings/<PRIM>-<cls>-<level>-<name>.md`), lists
    only known runners, scopes `flows` only to flows the test declares, and names a
    finding file that exists with `Status: open` (rule `expected-divergence`, error;
    rulings S17, S23)."""
    root = Path(root)
    test_files = sorted(root.glob("tests/**/test.yaml"))

    loaded: dict[Path, dict] = {}
    all_ids: set[str] = set()
    issues: list[LintIssue] = []
    for f in test_files:
        rel = str(f.relative_to(root))
        try:
            data = yaml.safe_load(f.read_text())
        except yaml.YAMLError as e:
            issues.append(LintIssue(rel, "test-schema", f"invalid YAML: {e}", "error"))
            continue
        try:
            validate_schema(data, "test")
        except jsonschema.ValidationError as e:
            issues.append(LintIssue(rel, "test-schema", _schema_message(e), "error"))
            continue
        loaded[f] = data
        all_ids.update(t["id"] for t in data["tests"])

    for f, data in loaded.items():
        rel = str(f.relative_to(root))
        readme = f.parent / "README.md"
        readme_text: str | None = None
        if readme.is_file():
            readme_text = readme.read_text()
        else:
            issues.append(LintIssue(rel, "tests-documented", "no sibling README.md", "error"))

        for t in data["tests"]:
            tid = t["id"]
            reasons = t.get("unsupported_reasons", {})
            for key in ("runners", "unsupported_reasons", "config_exclusions"):
                for runner in sorted(set(t.get(key, {})) - set(DECLARED_RUNNERS)):
                    issues.append(
                        LintIssue(
                            rel,
                            "runner-unknown",
                            f"{tid}: {key} names unknown runner {runner!r} "
                            f"(known: {', '.join(DECLARED_RUNNERS)})",
                            "error",
                        )
                    )
            cfgs = [c["cfg"] for c in t.get("configs", [])]
            if t["style"] != "vector":  # vector configs come from the generator
                cfgs = cfgs or ["default"]
                for runner, globs in t.get("config_exclusions", {}).items():
                    for g in globs:
                        if not any(fnmatch.fnmatchcase(c, g) for c in cfgs):
                            issues.append(
                                LintIssue(
                                    rel,
                                    "config-exclusions",
                                    f"{tid}: config_exclusions.{runner} glob {g!r} "
                                    f"matches no configuration of {cfgs}",
                                    "warning",
                                )
                            )
            for runner in DECLARED_RUNNERS:
                if runner not in t["runners"]:
                    issues.append(
                        LintIssue(
                            rel,
                            "runner-declared",
                            f"{tid}: runner {runner} is not declared in runners (it will "
                            'skip with reason "not declared")',
                            "warning",
                        )
                    )
            for runner, value in t["runners"].items():
                if value != "yes" and runner not in reasons:
                    issues.append(
                        LintIssue(
                            rel,
                            "runner-reasons",
                            f"{tid}: runner {runner} is declared {value!r} without an "
                            f"unsupported_reasons.{runner} entry",
                            "error",
                        )
                    )
            issues += _expected_divergence_issues(root, rel, data["primitive"], t)
            if readme_text is not None and tid not in readme_text:
                issues.append(
                    LintIssue(
                        rel,
                        "tests-documented",
                        f"test id {tid!r} not documented in {readme.name}",
                        "error",
                    )
                )
            for related_id in t.get("related", []):
                if related_id not in all_ids:
                    issues.append(
                        LintIssue(
                            rel,
                            "tests-documented",
                            f"related id {related_id!r} does not exist",
                            "warning",
                        )
                    )
    return issues


def _expected_divergence_issues(root: Path, rel: str, prim: str, t: dict) -> list[LintIssue]:
    tid = t["id"]
    known = (*DECLARED_RUNNERS, *DECLARATION_OF)
    out = []
    for e in t.get("expected_divergence", []):
        want = f"findings/{finding_id(prim, e['cls'], tid)}.md"
        problems = []
        if e["finding"] != want:
            problems.append(f"finding {e['finding']!r} is not the {e['cls']} finding id {want!r}")
        path = root / e["finding"]
        if not path.is_file():
            problems.append(f"finding {e['finding']!r} does not exist")
        elif (st := finding_status(path)) is None:
            problems.append(f"finding {e['finding']!r} has no Status: line")
        elif st != "open":
            problems.append(f"finding {e['finding']!r} is {st}, not open")
        for r in sorted(set(e["runners"]) - set(known)):
            problems.append(f"unknown runner {r!r}")
        for f in sorted(set(e.get("flows", [])) - set(t["flows"]) - {"rtl"}):
            problems.append(f"flow {f!r} is not one of the test's flows")
        out += [
            LintIssue(rel, "expected-divergence", f"{tid}: expected_divergence: {p}", "error")
            for p in problems
        ]
    return out


# --- bins-accounted / gaps-present --------------------------------------------------


def _valid_test_files(root: Path) -> list[tuple[str, dict]]:
    """``(relative path, data)`` of every schema-valid ``tests/**/test.yaml``. An invalid
    one is skipped here: ``check_tests_documented`` reports it (rule ``test-schema``)."""
    out = []
    for f in sorted(Path(root).glob("tests/**/test.yaml")):
        try:
            data = yaml.safe_load(f.read_text())
            validate_schema(data, "test")
        except (yaml.YAMLError, jsonschema.ValidationError):
            continue
        out.append((str(f.relative_to(root)), data))
    return out


def gap_bin(gap: str) -> str:
    """The bin a ``gaps`` entry accounts for: its leading token, up to the first
    whitespace or ``—`` (``"claim:FDRE.C8 — why"`` -> ``claim:FDRE.C8``; ruling S21)."""
    return re.split(r"\s|—", gap.strip(), maxsplit=1)[0]


def check_bins_accounted(root: Path) -> list[LintIssue]:
    """Spec §12 "every bin is covered or listed as a gap": for each ``test.yaml``, every
    bin of ``xut.status.coverage_bins`` (from the primitive's catalog entry) appears in
    some test's ``exercises`` or at the start of some ``gaps`` string (rule
    ``bins-accounted``, error). A ``test.yaml`` whose primitive has no catalog entry is
    an error too: its bins cannot be accounted for."""
    from xut.catalog.model import load_entry
    from xut.status import coverage_bins

    root = Path(root)
    issues = []
    for rel, data in _valid_test_files(root):
        prim, family = data["primitive"], data["family"]
        try:
            entry = load_entry(family, prim, root)
        except (OSError, yaml.YAMLError, jsonschema.ValidationError, XutError) as e:
            msg = f"no usable catalog entry for {prim}: {str(e).splitlines()[0]}"
            issues.append(LintIssue(rel, "bins-accounted", msg, "error"))
            continue
        exercised = {b for t in data["tests"] for b in t["exercises"]}
        gaps = [g for t in data["tests"] for g in t.get("gaps", [])]
        for b in coverage_bins(entry):
            if b not in exercised and b not in {gap_bin(g) for g in gaps}:
                issues.append(
                    LintIssue(
                        rel,
                        "bins-accounted",
                        f"bin {b} is in no test's exercises and starts no gaps entry",
                        "error",
                    )
                )
    return issues


def check_crosses(root: Path) -> list[LintIssue]:
    """Every attribute of a declared cross (catalog override ``crosses``, spec §4.2) is
    enumerated: a cross is covered pairwise over enumerated values (rule
    ``crosses-enumerated``, error). An override whose entry does not load (e.g. a cross
    naming an unknown attribute) is an error under the same rule."""
    from xut.catalog.model import is_enumerated, load_entry

    root = Path(root)
    issues = []
    for f in sorted(root.glob("catalog/*/*.overrides.yaml")):
        rel = str(f.relative_to(root))
        try:
            if "crosses" not in (yaml.safe_load(f.read_text()) or {}):
                continue
            entry = load_entry(f.parent.name, f.name.removesuffix(".overrides.yaml"), root)
        except (OSError, yaml.YAMLError, jsonschema.ValidationError, XutError) as e:
            msg = f"cannot load the entry: {str(e).splitlines()[0]}"
            issues.append(LintIssue(rel, "crosses-enumerated", msg, "error"))
            continue
        allowed = {a["name"]: a.get("allowed") or [] for a in entry.attributes}
        for cross in entry.crosses:
            for a in cross:
                if not is_enumerated(allowed[a]):
                    issues.append(
                        LintIssue(
                            rel,
                            "crosses-enumerated",
                            f"cross {cross}: {a} is not enumerated (allowed: {allowed[a]}); "
                            "crosses need enumerated values",
                            "error",
                        )
                    )
    return issues


def check_gaps_present(root: Path) -> list[LintIssue]:
    """Every test says what it misses (spec §1.6, controller ruling on review (b) #3): a
    test whose ``gaps`` is missing or empty, or has a blank entry, is an error (rule
    ``gaps-present``)."""
    return [
        LintIssue(rel, "gaps-present", f"{t['id']}: {why}", "error")
        for rel, data in _valid_test_files(root)
        for t in data["tests"]
        for why in (
            ["gaps is missing or empty"]
            if not t.get("gaps")
            else ["gaps has a blank entry"]
            if any(not g.strip() for g in t["gaps"])
            else []
        )
    ]


# --- status-schema -------------------------------------------------------------------


def check_status_files(root: Path) -> list[LintIssue]:
    """Every `status/**/*.yaml` validates against the status schema."""
    root = Path(root)
    issues = []
    for f in sorted(root.glob("status/**/*.yaml")):
        rel = str(f.relative_to(root))
        try:
            load_status(f)
        except (yaml.YAMLError, jsonschema.ValidationError) as e:
            issues.append(LintIssue(rel, "status-schema", str(e).splitlines()[0], "error"))
    return issues


# --- orchestration ---------------------------------------------------------------


def _tracked_files(root: Path) -> list[str]:
    """`git ls-files`: the tracked-file set the spdx rule runs over. A submodule shows up
    here as its own directory entry (mode 160000), never expanded into its contents."""
    proc = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True)
    return [line for line in proc.stdout.splitlines() if line]


def _ref_exists(root: Path, ref: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref], cwd=root, capture_output=True
    )
    return proc.returncode == 0


def _resolve_base(root: Path, base: str) -> tuple[str, str | None]:
    """`base` if it resolves, else the bare ref with a leading `origin/` stripped (with a
    warning), e.g. in a fresh clone with no fetch yet. Raises `GitError` (a RuntimeError;
    never a raw `CalledProcessError`) if neither resolves."""
    if _ref_exists(root, base):
        return base, None
    fallback = base.removeprefix("origin/")
    if fallback == base or not _ref_exists(root, fallback):
        raise GitError(
            f"_changed_files(): base ref {base!r} not found"
            + ("" if fallback == base else f", and fallback {fallback!r} not found either")
        )
    return fallback, f"{base} not found locally; diffing against {fallback} instead"


def _diff_names(root: Path, base: str, *extra: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", *extra, f"{base}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _changed_files(root: Path, base: str = "origin/main") -> tuple[list[str], str | None]:
    """Files this branch has touched relative to `<base>...HEAD` (controller ruling:
    `--branch` mode; `--base` lets CI diff against `origin/<PR base branch>` instead of
    `origin/main`). Falls back to the bare ref (stripping a leading `origin/`) with a
    warning if `base` isn't present locally (e.g. a fresh clone with no fetch yet).
    Raises `GitError` (a RuntimeError; never a raw `CalledProcessError`) if neither resolves.

    `--no-renames` is load-bearing for `check_branch_paths`: git's default rename
    detection would otherwise fold a delete+add pair into one `R###` entry and
    `--name-only` would print only the destination path, hiding the deleted source from
    ownership checking — letting a branch move a file it doesn't own into a path it does
    own undetected (review finding). With `--no-renames`, a rename always shows up as
    both its source (deleted) and destination (added) path, so both get checked.
    """
    base, warning = _resolve_base(root, base)
    return _diff_names(root, base), warning


def _added_files(root: Path, base: str) -> set[str]:
    """Files this branch ADDED relative to `<base>...HEAD` (`--diff-filter=A`, with the
    same base fallback as `_changed_files`). `--no-renames` again: a renamed file counts
    as its destination added and its source deleted, never as a silent "rename"."""
    base, _ = _resolve_base(root, base)
    return set(_diff_names(root, base, "--diff-filter=A"))


def lint(
    root: Path, branch_mode: bool, base: str = "origin/main"
) -> tuple[list[LintIssue], list[str]]:
    """Run every lint rule. Always runs spdx, tests-documented, bins-accounted,
    gaps-present, crosses-enumerated and status-schema over the whole tree; `branch_mode`
    additionally runs branch-paths and generated-files against the current branch's diff from
    `<base>...HEAD` (those two rules are meaningless without a diff — every file under
    `tools/**` is "on" a unit branch merely because it was inherited from `main`, not
    because that branch touched it). The current branch is `xut.status.current_branch()`,
    which honours the `XUT_BRANCH` env override CI needs for a pull_request event's
    detached-HEAD checkout.

    Returns `(issues, warnings)`; `warnings` never affect the exit code.
    """
    from xut.status import current_branch
    from xut.workunits import load_units

    root = Path(root)
    units = load_units(root)

    issues: list[LintIssue] = []
    warnings: list[str] = []

    tracked = _tracked_files(root)
    issues += check_spdx(root, tracked)
    issues += check_tests_documented(root)
    issues += check_bins_accounted(root)
    issues += check_gaps_present(root)
    issues += check_crosses(root)
    issues += check_status_files(root)

    if branch_mode:
        branch = current_branch()
        changed, warning = _changed_files(root, base)
        if warning:
            warnings.append(warning)
        added = _added_files(root, base) if branch.startswith("infra/") else set()
        issues += check_branch_paths(branch, changed, units, added)
        issues += check_generated_not_committed(changed, branch)

    return issues, warnings
