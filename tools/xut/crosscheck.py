# SPDX-License-Identifier: Apache-2.0
"""Cross-check every trace of a test and classify disagreements (spec §8).

``gather`` reads ``build/<flow>/<runner>/<model-source>/<test-id>/{result.json,trace.xtr}``
into ``View``s grouped by model source; ``classify`` runs once per model source, so
UNISIM traces are only ever compared like-for-like (spec §6.2).

- **Never agreement by omission.** Only configurations a runner actually ran (config
  status ``pass`` or ``fail``) are compared, and only where both sides ran them. Every
  missing, skipped or erroring result stays visible: in the matrix (a declared runner
  without a result is ``not-run``), and as an *issue* when it is an ``error`` or a
  ``fail`` that no disagreement explains.
- **A result must carry its evidence.** A pass/fail that ran a configuration but
  wrote no trace.xtr, a trace.xtr without result.json, and a configuration the golden
  model ran that a result omits are issues; one a runner skipped (``config_exclusions``)
  is a coverage note.
- **An expected divergence never masks** (spec §8 rev 3.1). Every disagreement is
  computed; one an ``expected_divergence`` entry lists is reported as
  ``known-divergence`` with the original class and the finding id. An entry matches
  only its exact finding id (``xut.testspec.finding_id``), the class, a superset of
  the finding's runners, and its optional ``model_sources``/``flows`` scope (ruling
  S17); an in-scope entry with another id is an issue.
- **Coverage gaps.** ``compare`` ignores ports only the actual trace has (the golden
  model may leave an output unmodelled); ``check`` lists them instead of dropping them.

``check`` returns a ``Report`` whose ``exit_code`` (ruling S23) is ``EXIT_FINDING``
(3) for any unlisted finding, otherwise ``EXIT_INCOMPLETE`` (4) for any issue (a result
that could not be compared or explained: insufficient evidence), otherwise 0. The CLI
also exits 4 when no selected test had two traces to compare. The codes never collide
with the generic ones: 1 is a user error (``XutError``: a selector matching nothing, a
bad test.yaml), 2 a click usage error.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from xut.formats.xtr import Mismatch, Trace, XtrError, compare, diff, load
from xut.golden import bit_prov
from xut.results import RAN, read_result
from xut.testspec import (
    SIMULATORS,
    TestCase,
    declared_runners,
    finding_id,
    finding_slug,
    prim_of,
    runner_key,
)

FINDING_CLASSES = (
    "doc-vs-model",
    "doc-gap",
    "sim-divergence",
    "x-dependence",
    "transform-bug",
    "flow-mismatch",
    "silicon-mismatch",
    "nondeterminism",
    "harness-error",
    "known-divergence",
)
X_OBSERVABLE = {
    "python": True,
    "xsim": True,
    "iverilog": True,
    "iverilog-vz": True,
    "verilator": False,
    "hw": False,
}
#: At most this many points are kept per finding (the count of the rest is noted).
MAX_POINTS = 200
REPORT_FORMAT = "xut-crosscheck 1"


@dataclass
class View:
    """One runner's result for a test: ``status`` is the result.json status, or
    ``not-run`` for a declared runner without a result."""

    flow: str
    runner: str
    status: str
    model_source: str | None
    trace: Trace | None
    result: dict

    @property
    def ran(self) -> set[str] | None:
        """Configurations this runner actually ran (``pass``/``fail``), whose samples
        may be compared; ``None`` (a synthetic view without ``configs``) means all."""
        cfgs = self.result.get("configs")
        if cfgs is None:
            return None
        return {c["cfg"] for c in cfgs if c.get("status") in RAN}


@dataclass(frozen=True)
class Finding:
    cls: str
    test_id: str
    flow: str
    model_source: str | None
    runners: tuple[str, ...]
    points: tuple[str, ...]
    expected: bool = False
    known_of: str | None = None  # original class when reported as known-divergence
    finding: str | None = None  # finding id (file stem) from expected_divergence

    @property
    def slug(self) -> str:
        return finding_slug(self.cls, self.test_id)

    def to_dict(self) -> dict:
        return {
            "cls": self.cls,
            "of": self.known_of,
            "finding": self.finding,
            "expected": self.expected,
            "flow": self.flow,
            "model_source": self.model_source,
            "runners": list(self.runners),
            "slug": self.slug,
            "points": list(self.points),
        }


def _f(
    cls: str,
    test_id: str,
    flow: str,
    ms: str | None,
    runners: Iterable[str],
    points: list[str],
) -> Finding:
    kept = points[:MAX_POINTS]
    if len(points) > MAX_POINTS:
        kept.append(f"... ({len(points) - MAX_POINTS} more)")
    return Finding(cls, test_id, flow, ms, tuple(sorted(runners)), tuple(kept))


# --- gathering -------------------------------------------------------------------------------


def _error_view(flow: str, runner: str, ms: str, data: dict, reason: str) -> View:
    return View(flow, runner, "error", ms, None, {**data, "status": "error", "reason": reason})


def _view(d: Path, flow: str, runner: str, ms: str, test_id: str) -> View:
    rf = read_result(d, flow, runner, ms, test_id)
    if rf is None:
        return _error_view(flow, runner, ms, {}, f"trace.xtr without result.json in {d}")
    if rf.problem is not None:
        return _error_view(flow, runner, ms, rf.data, rf.problem)
    data = rf.data
    trace = None
    if (d / "trace.xtr").is_file():
        try:
            trace = load(d / "trace.xtr")
        except XtrError as e:
            return _error_view(flow, runner, ms, data, f"malformed trace.xtr: {e}")
    ran = sorted(c["cfg"] for c in data["configs"] if c["status"] in RAN)
    if trace is None and data["status"] in RAN and ran:
        return _error_view(
            flow,
            runner,
            ms,
            data,
            f"reported {data['status']} for configuration(s) {', '.join(ran)} "
            "but wrote no trace.xtr",
        )
    return View(flow, runner, data["status"], ms, trace, data)


def gather(root: Path, test_id: str) -> dict[str, dict[tuple[str, str], View]]:
    """Per model source, the test's views keyed ``(flow, runner)``."""
    out: dict[str, dict[tuple[str, str], View]] = defaultdict(dict)
    build = Path(root, "build")
    dirs = {
        p.parent
        for pat in ("result.json", "trace.xtr")
        for p in build.glob(f"*/*/*/{test_id}/{pat}")
    }
    for d in sorted(dirs):
        ms, runner, flow = d.parent.name, d.parent.parent.name, d.parent.parent.parent.name
        out[ms][(flow, runner)] = _view(d, flow, runner, ms, test_id)
    return dict(out)


# --- classification ----------------------------------------------------------------------


def _cfg(label: str) -> str:
    return label.split("/", 1)[0]


def _restrict(t: Trace, cfgs: set[str] | None) -> Trace:
    if cfgs is None:
        return t
    out = Trace(dict(t.header))
    out.samples = {lbl: p for lbl, p in t.samples.items() if _cfg(lbl) in cfgs}
    out.prov = {lbl: p for lbl, p in t.prov.items() if lbl in out.samples}
    return out


def _pair(a: View, b: View) -> tuple[Trace, Trace]:
    """Both traces, restricted to the configurations both runners ran."""
    ra, rb = a.ran, b.ran
    common = ra if rb is None else rb if ra is None else ra & rb
    assert a.trace is not None and b.trace is not None
    return _restrict(a.trace, common), _restrict(b.trace, common)


def _has_trace(v: View | None) -> bool:
    return v is not None and v.trace is not None and (v.ran is None or bool(v.ran))


def _bit_prov(m: Mismatch) -> str | None:
    if m.prov is None or m.bit < 0:
        return m.prov
    try:
        return bit_prov(m.prov, m.bit)
    except IndexError:
        return m.prov


def _point(m: Mismatch) -> str:
    """A golden-vs-actual point with its bit's own provenance."""
    where = f"{m.label} {m.port}" + (f"[{m.bit}]" if m.bit >= 0 else "")
    prov = _bit_prov(m)
    tag = f" ({prov})" if prov else ""
    kind = "" if m.kind == "value" else f" [{m.kind}]"
    return f"{where}: expected {m.expected}, got {m.actual}{tag}{kind}"


def _observes(v: View, m: Mismatch) -> bool:
    """Whether runner ``v`` could have disagreed at golden point ``m``: it ran the
    point's configuration and (for a 2-state runner) the expected bit is not x/z."""
    if v.ran is not None and _cfg(m.label) not in v.ran:
        return False
    return X_OBSERVABLE.get(v.runner, True) or m.expected not in ("x", "z")


def _golden_vs_sims(
    test_id: str,
    ms: str | None,
    exp: View,
    group: dict[str, View],
    diverged: set[tuple],
    sim_points: list[str],
    issues: list[str],
) -> list[Finding]:
    per_point: dict[tuple, dict[str, Mismatch]] = defaultdict(dict)
    for r, v in group.items():
        e, a = _pair(exp, v)
        for m in compare(e, a, x_observable=X_OBSERVABLE.get(r, True)):
            per_point[(m.label, m.port, m.bit, m.kind)][r] = m
    doc: list[str] = []
    gap: list[str] = []
    doc_rs: set[str] = set()
    gap_rs: set[str] = set()
    assert exp.trace is not None
    order = {lbl: i for i, lbl in enumerate(exp.trace.samples)}  # simulated-time order
    for pt, by_runner in sorted(
        per_point.items(), key=lambda kv: (order.get(kv[0][0], len(order)), kv[0])
    ):
        if pt[:3] in diverged:
            continue
        m = next(iter(by_runner.values()))
        observers = {r for r, v in group.items() if _observes(v, m)}
        if set(by_runner) != observers:  # some observing sims agree with the golden
            for r in sorted(by_runner):
                sim_points.append(f"python vs {r} only: {_point(by_runner[r])}")
            continue
        prov = _bit_prov(m) or ""
        if m.kind != "value" or m.bit < 0:
            issues.append(
                f"{ms} rtl: golden and every simulator ({', '.join(sorted(group))}) "
                f"disagree structurally: {m}"
            )
        elif prov.startswith("doc:"):
            doc.append(_point(m))
            doc_rs |= observers
        elif prov.startswith("inferred:"):
            gap.append(_point(m))
            gap_rs |= observers
        else:
            issues.append(f"{ms} rtl: provenance {prov!r} is neither doc: nor inferred: ({m})")
    out = []
    if doc:
        out.append(_f("doc-vs-model", test_id, "rtl", ms, doc_rs, doc))
    if gap:
        out.append(_f("doc-gap", test_id, "rtl", ms, gap_rs, gap))
    return out


def classify(
    test_id: str,
    views: dict[tuple[str, str], View],
    expected_divergence: tuple[dict, ...] | list[dict] = (),
    issues: list[str] | None = None,
) -> list[Finding]:
    """The findings among one model source's views. Disagreements that are no finding
    class (structural golden-vs-simulator differences, an unknown provenance) are
    appended to ``issues`` when given."""
    issues = [] if issues is None else issues
    out: list[Finding] = []
    exp = views.get(("rtl", "python"))
    sims: dict[str, dict[str, View]] = defaultdict(dict)
    for (flow, runner), v in views.items():
        if runner in SIMULATORS and _has_trace(v):
            sims[flow][runner] = v
    for flow, group in sorted(sims.items()):
        ms = next(iter(group.values())).model_source
        diverged: set[tuple] = set()
        points: list[str] = []
        for a, b in combinations(sorted(group), 2):
            ta, tb = _pair(group[a], group[b])
            for m in diff(ta, tb, a_x=X_OBSERVABLE[a], b_x=X_OBSERVABLE[b]):
                diverged.add((m.label, m.port, m.bit))
                points.append(f"{a} vs {b}: {m}")
        doc_findings = []
        if flow == "rtl" and exp is not None and _has_trace(exp):
            doc_findings = _golden_vs_sims(test_id, ms, exp, group, diverged, points, issues)
        if points:
            out.append(_f("sim-divergence", test_id, flow, ms, group, points))
        out += doc_findings
    for (flow, runner), v in views.items():
        if runner == "verilator" and v.result.get("x_dependence"):
            seeds = (v.result.get("seeds") or {}).get("x")
            out.append(
                _f(
                    "x-dependence",
                    test_id,
                    flow,
                    v.model_source,
                    ["verilator"],
                    [f"X seeds {seeds} disagree"],
                )
            )
        if (
            runner == "iverilog-vz"
            and _has_trace(v)
            and _has_trace(iv := views.get((flow, "iverilog")))
        ):
            assert iv is not None
            pts = [str(m) for m in diff(*_pair(iv, v))]
            if pts:
                out.append(
                    _f(
                        "transform-bug",
                        test_id,
                        flow,
                        v.model_source,
                        ["iverilog", "iverilog-vz"],
                        pts,
                    )
                )
        if flow != "rtl" and runner in SIMULATORS and _has_trace(v):
            ref = views.get(("rtl", runner))
            if _has_trace(ref):
                assert ref is not None
                x = X_OBSERVABLE[runner]
                pts = [str(m) for m in diff(*_pair(ref, v), a_x=x, b_x=x)]
                if pts:
                    out.append(_f("flow-mismatch", test_id, flow, v.model_source, [runner], pts))
        if runner == "hw":
            hw = v.result.get("hw") or {}
            if hw.get("selftest") == "fail":
                out.append(_f("harness-error", test_id, flow, None, ["hw"], ["self-test failed"]))
                continue
            if hw.get("repeats_differ"):
                out.append(
                    _f(
                        "nondeterminism",
                        test_id,
                        flow,
                        None,
                        ["hw"],
                        [f"{hw.get('repeats')} runs disagree"],
                    )
                )
            if exp is not None and _has_trace(exp) and _has_trace(v):
                pts = [_point(m) for m in compare(*_pair(exp, v), x_observable=False)]
                if pts:
                    out.append(_f("silicon-mismatch", test_id, flow, None, ["hw"], pts))
    return [_mark(f, tuple(expected_divergence), issues) for f in out]


def covers(e: dict, f: Finding) -> bool:
    """Whether ``expected_divergence`` entry ``e`` is in scope for finding ``f``: same
    class, its ``runners`` a superset of the finding's, and within its optional
    ``model_sources``/``flows`` scope (ruling S17). The id is checked by ``_mark``."""
    return (
        e.get("cls") == f.cls
        and set(e.get("runners") or ()) >= set(f.runners)
        and ("model_sources" not in e or f.model_source in e["model_sources"])
        and ("flows" not in e or f.flow in e["flows"])
    )


def _mark(f: Finding, expected: tuple[dict, ...], issues: list[str]) -> Finding:
    """A listed divergence is still reported, as known-divergence (never masked). An
    entry matches only with the exact finding id (ruling S17); one in scope under
    another id is an issue, never a match."""
    want = finding_id(prim_of(f.test_id), f.cls, f.test_id)
    for e in expected:
        if not covers(e, f):
            continue
        fid = Path(e["finding"]).stem
        if fid != want:
            issues.append(
                f"expected_divergence {e['finding']} is in scope for a {f.cls} finding "
                f"({f.flow} / {f.model_source or 'n/a'}) but is not its id {want}: not matched"
            )
            continue
        return Finding(
            "known-divergence",
            f.test_id,
            f.flow,
            f.model_source,
            f.runners,
            f.points,
            True,
            f.cls,
            fid,
        )
    return f


# --- the matrix --------------------------------------------------------------------------


def matrix(views: dict[tuple[str, str], View]) -> str:
    """One model source's views as a markdown table (flow x runner), then the reason
    of every result that is not a pass."""
    flows = sorted({f for f, _ in views}, key=lambda f: (f != "rtl", f))
    runners = sorted({r for _, r in views}, key=runner_key)
    lines = [
        "| flow | " + " | ".join(runners) + " |",
        "|---|" + "---|" * len(runners),
    ]
    for flow in flows:
        cells = [views[(flow, r)].status if (flow, r) in views else "" for r in runners]
        lines.append(f"| {flow} | " + " | ".join(cells) + " |")
    notes = [
        f"- {flow}/{r}: {v.status}: {v.result.get('reason') or 'no reason recorded'}"
        for flow in flows
        for r in runners
        if (v := views.get((flow, r))) is not None and v.status != "pass"
    ]
    return "\n".join(lines + ([""] + notes if notes else [])) + "\n"


# --- finding stubs -----------------------------------------------------------------------


def _head(root: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True
    )
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown commit"


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def finding_path(root: Path, prim: str, f: Finding) -> Path:
    return Path(root) / "findings" / f"{prim}-{f.slug}.md"


def write_finding(root: Path, prim: str, f: Finding) -> Path | None:
    """Write the ``findings/<PRIM>-<slug>.md`` stub (spec §8 "Recording") and return
    its path. Never overwrites: for an existing file it returns ``None`` (after
    ``record_finding``'s append-only ``Also seen`` line when the finding is seen on a
    new flow / model source). A ``known-divergence`` returns ``None`` without writing,
    because its finding already exists (``f.finding``)."""
    action, p = record_finding(root, prim, f)
    return p if action == "wrote" else None


def _where(f: Finding) -> str:
    return f"{f.flow} / {f.model_source or 'n/a'}"


def record_finding(root: Path, prim: str, f: Finding) -> tuple[str, Path | None]:
    """``("wrote", path)`` for a new stub; ``("recorded", path)`` when an existing
    finding file gained an ``- Also seen: <flow> / <ms> (<date> at <head>)`` line (a
    slug is per test and class, so two model sources or flows share one file; the file
    is only ever appended to); ``("exists", path)`` when it already names that
    flow / model source; ``("known", None)`` for a known-divergence."""
    if f.cls == "known-divergence":
        return "known", None
    p = finding_path(root, prim, f)
    if p.exists():
        lines = p.read_text().splitlines()
        where = _where(f)
        if f"- Flow / model source: {where}" in lines or any(
            ln.startswith(f"- Also seen: {where} (") for ln in lines
        ):
            return "exists", p
        with p.open("a") as fh:
            fh.write(f"- Also seen: {where} ({_today()} at {_head(root)})\n")
        return "recorded", p
    evidence = "\n".join(f"- {pt}" for pt in f.points)
    text = (
        f"# {prim}: {f.cls} in {f.test_id}\n"
        "\n"
        f"- Class: {f.cls}\n"
        f"- Test: {f.test_id}\n"
        f"- Flow / model source: {f.flow} / {f.model_source or 'n/a'}\n"
        f"- Runners: {', '.join(f.runners)}\n"
        f"- First seen: {_today()} at {_head(root)}\n"
        "- Status: open\n"
        "\n"
        "## Evidence\n"
        "\n"
        f"{evidence}\n"
        "\n"
        "## Analysis\n"
        "\n"
        "Not yet analysed. Explain the divergence against the cited UG953 page, then either\n"
        "correct the golden model (with its provenance) or add an `expected_divergence`\n"
        "entry to test.yaml pointing here. Never weaken the test (spec §8).\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x") as fh:  # exclusive: never overwrite, even in a race
        fh.write(text)
    return "wrote", p


# --- one test, end to end ----------------------------------------------------------------

#: Exit codes (ruling S23); 1 (``XutError``) and 2 (click usage) keep their generic meaning.
EXIT_FINDING = 3
EXIT_INCOMPLETE = 4

VERDICTS = ("not-run", "uncompared", "agree", "known-divergence", "incomplete", "divergence")


@dataclass
class Report:
    case: TestCase
    views: dict[str, dict[tuple[str, str], View]]
    findings: list[Finding] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    unmatched_expected: list[str] = field(default_factory=list)
    compared: bool = False

    @property
    def unlisted(self) -> list[Finding]:
        return [f for f in self.findings if f.cls != "known-divergence"]

    @property
    def verdict(self) -> str:
        if self.unlisted:
            return "divergence"
        if self.issues:
            return "incomplete"
        if self.findings:
            return "known-divergence"
        if self.compared:
            return "agree"
        return "uncompared" if self.views else "not-run"

    @property
    def exit_code(self) -> int:
        if self.unlisted:
            return EXIT_FINDING
        return EXIT_INCOMPLETE if self.issues else 0

    def to_dict(self) -> dict:
        return {
            "format": REPORT_FORMAT,
            "test_id": self.case.id,
            "prim": self.case.prim,
            "verdict": self.verdict,
            "model_sources": {
                ms: {
                    f"{flow}/{runner}": {"status": v.status, "reason": v.result.get("reason")}
                    for (flow, runner), v in sorted(vs.items())
                }
                for ms, vs in sorted(self.views.items())
            },
            "findings": [f.to_dict() for f in self.findings],
            "issues": self.issues,
            "coverage_gaps": self.coverage_gaps,
            "unmatched_expected": self.unmatched_expected,
        }


def _coverage_gaps(ms: str, views: dict[tuple[str, str], View]) -> list[str]:
    """Ports a runner observed that the golden model does not model, per flow and per
    configuration (``compare`` ignores them, so they are listed here)."""
    exp = views.get(("rtl", "python"))
    if not _has_trace(exp):
        return []
    assert exp is not None and exp.trace is not None
    modelled: dict[str, set[str]] = defaultdict(set)
    for lbl, ports in exp.trace.samples.items():
        modelled[_cfg(lbl)] |= set(ports)
    extra: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for (flow, runner), v in views.items():
        if runner != "python" and _has_trace(v):
            assert v.trace is not None
            for lbl, ports in _restrict(v.trace, v.ran).samples.items():
                for p in set(ports) - modelled[_cfg(lbl)]:
                    extra[(flow, p)][_cfg(lbl)].add(runner)
    out = []
    for (flow, p), by_cfg in sorted(extra.items()):
        runners = sorted(set().union(*by_cfg.values()), key=runner_key)
        out.append(
            f"{ms} {flow}: {p} observed by {', '.join(runners)} in cfg "
            f"{', '.join(sorted(by_cfg))}, not modelled by the golden model"
        )
    return out


def _config_coverage(ms: str, views: dict[tuple[str, str], View]) -> tuple[list[str], list[str]]:
    """``(notes, issues)``: every configuration the golden model ran must be visible
    in every other result. One a runner skipped (``config_exclusions``) is a coverage
    note; one missing from its result entirely is an issue."""
    exp = views.get(("rtl", "python"))
    golden = sorted(exp.ran or ()) if exp is not None and exp.status in RAN else []
    notes: list[str] = []
    issues: list[str] = []
    for (flow, runner), v in sorted(views.items()):
        listed = {c.get("cfg"): c for c in v.result.get("configs") or []}
        if runner == "python" or not listed:
            continue  # no configurations: not run, skipped whole, or an error (an issue)
        for g in golden:
            c = listed.get(g)
            if c is None:
                issues.append(
                    f"{ms} {flow}/{runner}: cfg {g}, run by the golden model, is absent "
                    "from its result"
                )
            elif c.get("status") == "skip":
                notes.append(
                    f"{ms} {flow}/{runner}: cfg {g} skipped: "
                    f"{c.get('reason') or 'no reason recorded'}"
                )
    return notes, issues


#: Classes that compare values: a fail is explained by one of these naming its runner.
VALUE_CLASSES = (
    "sim-divergence",
    "doc-vs-model",
    "doc-gap",
    "transform-bug",
    "flow-mismatch",
    "silicon-mismatch",
)


def _explained(v: View, findings: list[Finding]) -> bool:
    return any(
        (f.known_of or f.cls) in VALUE_CLASSES
        and v.runner in f.runners
        and f.flow == v.flow
        and f.model_source in (v.model_source, None)
        for f in findings
    )


def _result_issues(ms: str, v: View, findings: list[Finding]) -> list[str]:
    where = f"{ms} {v.flow}/{v.runner}"
    cfg_errors = [
        f"{where}: cfg {c.get('cfg')}: error: {c.get('reason') or 'no reason recorded'}"
        for c in v.result.get("configs") or []
        if c.get("status") == "error"
    ]
    if cfg_errors:
        return cfg_errors
    reason = v.result.get("reason") or "no reason recorded"
    if v.status == "error":
        return [f"{where}: error: {reason}"]
    if v.status == "fail" and not _explained(v, findings):
        return [f"{where}: fail not explained by any disagreement: {reason}"]
    return []


def check(root: Path, case: TestCase, model_source: str | None = None) -> Report:
    """Gather, classify per model source and account for every result of ``case``;
    only ``model_source``'s results when it is given."""
    gathered = gather(root, case.id)
    if model_source is not None:
        gathered = {ms: v for ms, v in gathered.items() if ms == model_source}
    rep = Report(case, gathered)
    matched: set[str] = set()
    for ms, views in sorted(gathered.items()):
        for flow in dict.fromkeys(["rtl", *case.flows]):
            for r in declared_runners(case, flow):
                if (flow, r) not in views:
                    views[(flow, r)] = View(
                        flow, r, "not-run", ms, None, {"reason": "declared, but no result.json"}
                    )
        found = classify(case.id, views, case.expected_divergence, rep.issues)
        rep.findings += found
        matched |= {f.finding for f in found if f.finding}
        rep.compared |= sum(_has_trace(v) for v in views.values()) >= 2
        notes, cfg_issues = _config_coverage(ms, views)
        rep.coverage_gaps += _coverage_gaps(ms, views) + notes
        rep.issues += cfg_issues
        for _, v in sorted(views.items()):
            rep.issues += _result_issues(ms, v, found)
    for e in case.expected_divergence:
        if not (Path(root) / e["finding"]).is_file():
            rep.issues.append(f"expected_divergence names {e['finding']}, which does not exist")
        if Path(e["finding"]).stem not in matched:
            rep.unmatched_expected.append(e["finding"])
    return rep


def write_report(root: Path, rep: Report) -> Path:
    p = Path(root) / "build" / "crosscheck" / f"{rep.case.id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep.to_dict(), indent=1) + "\n")
    return p


def render(rep: Report, max_points: int = 10) -> str:
    """The human-readable report of one test: matrix per model source, findings,
    issues, coverage gaps."""
    out = [f"## {rep.case.id}: {rep.verdict}", ""]
    if not rep.views:
        declared = ", ".join(declared_runners(rep.case, "rtl")) or "none"
        out += [f"not-run: no result under build/ for any runner (declared: {declared})", ""]
    for ms, views in sorted(rep.views.items()):
        out += [f"### model source {ms}", "", matrix(views)]
    for f in rep.findings:
        head = (
            f.cls
            if f.cls != "known-divergence"
            else (f"known-divergence (of {f.known_of}, finding {f.finding})")
        )
        out.append(
            f"{'known' if f.expected else 'UNLISTED'}: {head} [{f.flow} / "
            f"{f.model_source or 'n/a'}] runners {', '.join(f.runners)}: "
            f"{len(f.points)} point(s)"
        )
        out += [f"    {p}" for p in f.points[:max_points]]
        if len(f.points) > max_points:
            out.append(f"    ... {len(f.points) - max_points} more in the JSON report")
    out += [f"issue: {i}" for i in rep.issues]
    out += [f"coverage gap: {g}" for g in rep.coverage_gaps]
    out += [
        f"note: expected_divergence {e} matched no disagreement (fixed?)"
        for e in rep.unmatched_expected
    ]
    return "\n".join(out).rstrip() + "\n"
