# SPDX-License-Identifier: Apache-2.0
"""What every work unit's metadata generator and guard tests share (ruling S53).

A unit's ``<stem>_tests.py`` builds its test entries with ``entry``, renders its files
with ``dump_test_yaml``/``render_readme``, and describes itself as a ``Unit``; its
``test_<stem>_tests.py`` is one line, ``class TestUnit(UnitGuards): unit = UNIT``. A unit
never copies this code, or the flops unit's.

- The standard ``unsupported_reasons`` (``SV_PY`` ... ``HW_GSR``) and ``runners``.
- Bin names from the catalog (``class_bins``), never hand-rolled.
- ``vector_reach``: what each configuration of a vector test reaches, through the python
  runner's own generation (``generate``, the ``xut run`` seed) and replay
  (``replay_config``), and whether every sampled bit is documented (``pure``).
- ``doc_mismatches``: how many documented bits a model variant gets wrong over a vector
  test; ``mutant_fails``: whether a variant that breaks one claimed rule fails a
  documented bit in some configuration that credits that claim, or with ``every`` in each
  one (rulings S55, S55a). Both compare per-bit provenance tags.
- ``cases``: a primitive's discovered test cases.
- ``UnitGuards``: drift of every rendered file, presence, schema and reasons, generators,
  reach, bins accounted (``xut.lint.gap_bin``), pure crediting (rulings S44, S52) and a
  failing mutant per declared claim (ruling S55): in one crediting configuration of a
  read claim, in every one of an event claim (``Mutant(event=True)``, ruling S55a).
  Only tests that declare the claim in ``exercises`` are checked, because status credits
  only declared bins.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import yaml

from xut.catalog import model as catalog_model
from xut.catalog.model import CatalogEntry
from xut.testspec import DECLARED_RUNNERS, TestCase, discover

if TYPE_CHECKING:
    import pytest

    from xut.formats.xtr import Trace
    from xut.formats.xvec import Vec
    from xut.wrap import DutMap
    from xut_models.base import Model

#: ``(value, reason)``: a runner declaration other than ``"yes"``.
Reason = tuple[str, str]
#: ``(runners, unsupported_reasons)`` of one test.
Declared = tuple[dict[str, str], dict[str, str]]

ALL_FLOWS = ("rtl", "vivado", "yosys", "openxc7", "vpr")
SV_PY: Reason = ("no", "self-checking sv testbench; there is no golden-model replay")
SV_HW: Reason = ("unsupported", "sv testbenches are simulation-only (spec §4.3)")
X_VL: Reason = (
    "unsupported",
    "2-state simulator: x stimulus is randomised per X seed (spec §5.6), so the "
    "undocumented x checkpoints cannot be compared",
)
CO_PY: Reason = ("no", "the cocotb test compares against the golden model itself")
CO_XS: Reason = ("unsupported", "cocotb has no xsim backend (spec §4.3)")
CO_HW: Reason = (
    "unsupported",
    "cocotb runs in simulation; failing seeds are frozen into vector tests",
)
VL_REJ: Reason = ("unsupported", "a 2-state simulator cannot represent an x attribute value")
HW_REJ: Reason = ("unsupported", "rejection of an illegal attribute is a simulation-model check")
HW_GSR: Reason = ("unsupported", "GSR pulses need the GSR-immune harness state of spec §7.2")
HW_PAD: Reason = (
    "unsupported",
    "the primitive sits on IOB/ILOGIC/OLOGIC/IDELAY/BUFIO/BUFR sites: it needs the pad "
    "harness of spec §7.3",
)


def runners(**over: Reason) -> Declared:
    """Every declared runner ``"yes"`` except those in ``over``, with their reasons."""
    declared = {r: over[r][0] if r in over else "yes" for r in DECLARED_RUNNERS}
    return declared, {r: reason for r, (_, reason) in over.items()}


def claims(prim: str, *ns: int) -> list[str]:
    return [f"claim:{prim}.C{n}" for n in ns]


def class_bins(catalog_entry: CatalogEntry, port: str, *events: str) -> list[str]:
    """``port:<P>`` and the named class bins of one port (all of them when none is
    named), from ``xut.status.port_class_bins``."""
    from xut.status import port_class_bins

    p = next(p for p in catalog_entry.ports if p["name"] == port)
    by_event = {b.rsplit(":", 1)[1]: b for b in port_class_bins(p)}
    return [f"port:{port}", *(by_event[e] for e in events or by_event)]


def entry(
    family: str,
    prim: str,
    level: str,
    name: str,
    style: str,
    source: str,
    exercises: Sequence[str],
    *,
    gaps: Sequence[str],
    sampling: Mapping[str, list] | None = None,
    declared: Declared | None = None,
    flows: Sequence[str] = ALL_FLOWS,
    configs: Sequence[dict] = (),
    related: Sequence[str] = (),
) -> dict[str, Any]:
    """One ``test.yaml`` test, in the schema's key order. Every test says what it
    misses (lint rule gaps-present); every non-``"yes"`` runner has its reason."""
    if not gaps:
        raise ValueError(f"{prim}.{level}.{name}: every test must say what it misses")
    runs, reasons = declared or runners()
    e: dict[str, Any] = {
        "id": f"{family}.{prim}.{level}.{name}",
        "level": level,
        "style": style,
        "source": source,
        "exercises": list(dict.fromkeys(exercises)),
        "attr_sampling": dict(sampling or {}),
        "runners": runs,
    }
    if reasons:
        e["unsupported_reasons"] = reasons
    e["flows"] = list(flows)
    e["related"] = list(related)
    e["gaps"] = list(gaps)
    if configs:
        e["configs"] = list(configs)
    return e


class _NoAliasDumper(yaml.SafeDumper):
    """Every test written out in full: no YAML anchors or aliases (flops review M4)."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def dump_test_yaml(doc: dict, generator: str) -> str:
    """``doc`` as a committed ``test.yaml``: the SPDX line, a GENERATED line naming
    ``generator`` (a repository path), and the strings "yes"/"no" quoted."""
    header = f"# SPDX-License-Identifier: Apache-2.0\n# GENERATED by {generator}; edit that file.\n"
    return header + yaml.dump(
        doc, Dumper=_NoAliasDumper, sort_keys=False, width=100, allow_unicode=True
    )


def cell(test: dict, runner: str) -> str:
    """A runner-support table cell: ``yes``, or the value and its reason."""
    v = test["runners"][runner]
    return v if v == "yes" else f"{v}: {test['unsupported_reasons'][runner]}"


def run_block(prim: str) -> list[str]:
    """The README's "How to run": the heavy command under the per-user heavy lock and a
    capped scope (AGENTS.md §10.1), then crosscheck and record."""
    p = prim.lower()
    return [
        "```bash",
        'flock "$XDG_RUNTIME_DIR/xut-heavy.lock" systemd-run --user --scope \\',
        "  --slice=vivado.slice --unit=xut-run-$(date +%s) \\",
        "  -p MemoryMax=32G -p MemorySwapMax=0 -- \\",
        f"  uv run xut run {prim} --jobs 16 > .cache/run-{p}.log 2>&1",
        f"uv run xut crosscheck {prim} > .cache/xc-{p}.log 2>&1",
        f"uv run xut status record {prim} > .cache/status-{p}.log 2>&1",
        "```",
    ]


def render_readme(
    *,
    prim: str,
    title: str,
    reference: str,
    overview: str,
    tests: Sequence[tuple[dict, str]],
    oracle: Sequence[str],
    known_gaps: Sequence[str],
    root: Path,
) -> str:
    """A primitive's README with every section of docs/templates/primitive-README.md.
    ``tests`` pairs each test.yaml entry with why it is useful; findings are the open
    and closed ``findings/<PRIM>-*.md`` files, linked."""
    findings = sorted((root / "findings").glob(f"{prim}-*.md"))
    lines = [f"# {prim} — {title}", "", reference, "", "## Overview", "", overview, ""]
    lines += ["## Tests", "", "| ID | Level | Style | Exercises |", "|---|---|---|---|"]
    lines += [
        f"| `{e['id']}` | {e['level']} | {e['style']} | {', '.join(e['exercises'])} |"
        for e, _ in tests
    ]
    lines += ["", "## Why each test is useful, and what it misses", ""]
    for e, why in tests:
        lines.append(f"- `{e['id']}`: {why}")
        lines += [f"  - Misses: {g}" for g in e["gaps"]]
    lines += ["", "## Oracle", "", *(f"- {o}" for o in oracle), ""]
    lines += ["## Known gaps (all tests)", "", *(f"- {g}" for g in known_gaps)]
    lines += [f"- {g}" for g in dict.fromkeys(g for e, _ in tests for g in e["gaps"])]
    lines += ["", "## Runner support and expected divergences", ""]
    lines += ["| Test | " + " | ".join(DECLARED_RUNNERS) + " |"]
    lines += ["|---|" + "---|" * len(DECLARED_RUNNERS)]
    lines += [
        f"| `{e['id']}` | " + " | ".join(cell(e, r) for r in DECLARED_RUNNERS) + " |"
        for e, _ in tests
    ]
    lines += ["", "Findings:" if findings else "Findings: none recorded.", ""]
    lines += [f"- [{f.stem}](../../../../findings/{f.name})" for f in findings]
    lines += ["", "## Related tests", ""]
    lines += [
        f"- `{e['id']}`: " + (", ".join(f"`{r}`" for r in e["related"]) or "none") for e, _ in tests
    ]
    lines += ["", "## How to run", "", *run_block(prim), ""]
    return "\n".join(lines)


# --- reach -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigReach:
    """One configuration of a vector test, replayed through the golden model."""

    cfg: str
    bins: frozenset[str]
    #: every sampled bit's provenance is ``doc:`` (none ``inferred:``): the configuration
    #: can credit claims whatever the inferred details turn out to be (ruling S52)
    pure: bool


@dataclass(frozen=True)
class _Replayed:
    reach: ConfigReach
    vec: Vec
    m: DutMap
    trace: Trace


def _documented(prov: Mapping[str, Mapping[str, str]]) -> bool:
    return all(
        tag.startswith("doc:")
        for ports in prov.values()
        for token in ports.values()
        for tag in token.split(",")
    )


def _replay_all(case: TestCase, root: Path) -> list[_Replayed]:
    from xut.modelsrc import ModelSource
    from xut.runners.base import RunContext
    from xut.runners.python import generate, replay_config
    from xut.wrap import build_map
    from xut_models import registry

    ctx = RunContext(root, "rtl", ModelSource("golden", root))
    catalog_entry = catalog_model.load_entry(case.family, case.prim, root)
    model_cls = registry.get(case.family, case.prim)
    out = []
    for vec, spec in generate(case, ctx):
        if vec.expect == "reject":
            continue
        m = build_map(spec)
        trace, bins = replay_config(catalog_entry, model_cls, vec, m)
        out.append(
            _Replayed(ConfigReach(vec.cfg, frozenset(bins), _documented(trace.prov)), vec, m, trace)
        )
    return out


def vector_reach(case: TestCase, root: Path) -> list[ConfigReach]:
    """Every non-reject configuration of vector test ``case``, generated and replayed
    exactly as ``xut run --runner python`` does (``generate`` with the default seed,
    ``replay_config``).

    TODO (ruling S57): only the default seed is checked. ``xut status record`` warns
    when it credits a python run made with another ``--seed``; refuse it instead once
    ``xut freeze-seed`` exists."""
    return [r.reach for r in _replay_all(case, root)]


def _doc_diffs(want: Trace, got: Trace) -> Iterator[tuple[str, str, int]]:
    """(sample, port, bit) of every bit ``want`` documents (``doc:``, per-bit tags, LSB
    first) on which ``got`` shows the other defined value. A ``-``, x or z on either side
    never counts (ruling S57.1): that is the least-observable semantics of
    ``xtr.compare`` against a 2-state runner, so a counted bit is one every runner's
    crosscheck would catch."""
    for label, ports in want.samples.items():
        for port, bits in ports.items():
            tags = want.prov[label][port].split(",")
            for i, (w, g) in enumerate(
                zip(reversed(bits), reversed(got.samples[label][port]), strict=True)
            ):
                tag = tags[i] if len(tags) > 1 else tags[0]
                if tag.startswith("doc:") and w in "01" and g in "01" and w != g:
                    yield label, port, i


def _doc_mismatch(want: Trace, got: Trace) -> bool:
    """``got`` differs from ``want`` on a bit ``want`` documents."""
    return next(_doc_diffs(want, got), None) is not None


def doc_mismatches(case: TestCase, root: Path, model: type[Model]) -> int:
    """How many documented bits ``model`` gets wrong over every configuration of vector
    test ``case``, generated and replayed as ``vector_reach`` does (0 for the golden
    model itself)."""
    from xut.golden import replay

    return sum(
        sum(1 for _ in _doc_diffs(r.trace, replay(model, r.vec, r.m)[0]))
        for r in _replayed(root, case)
    )


def mutant_fails(
    case: TestCase, root: Path, claim: str, mutant: type[Model], *, every: bool = False
) -> bool | None:
    """Whether ``mutant`` (a model that breaks the rule of ``claim``) fails a documented
    bit in some configuration of vector test ``case`` that credits ``claim`` (with
    ``every``: in each one); ``None`` when no configuration of ``case`` credits it
    (rulings S55, S55a)."""
    from xut.golden import replay

    crediting = [r for r in _replayed(root, case) if f"claim:{claim}" in r.reach.bins]
    if not crediting:
        return None
    caught = (_doc_mismatch(r.trace, replay(mutant, r.vec, r.m)[0]) for r in crediting)
    return all(caught) if every else any(caught)


@dataclass(frozen=True)
class Mutant:
    """A unit's mutant for one claim: ``factory`` turns the golden model class into a
    model breaking exactly that claim's rule. ``event`` marks an event claim (a clock
    edge, a shift, a hold), whose every crediting configuration must catch the mutant;
    a read claim's (a stuck-at output agrees on reads of its own value) needs only one
    (ruling S55a)."""

    factory: Callable[[type[Model]], type[Model]]
    event: bool = False


# --- the guard set ---------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    """A work unit as its guards see it."""

    name: str
    family: str
    root: Path
    group_dir: Path  # tests/<family>/<group>
    prims: tuple[str, ...]
    #: prim -> {path relative to the primitive's directory: rendered text}; test.yaml,
    #: README.md and every wrapper file the generator writes
    render: Callable[[str], dict[str, str]]
    #: prim -> test.yaml function name -> generator
    generators: Callable[[str], Mapping[str, Callable]]
    #: prim -> {claim id: its Mutant} (rulings S55, S55a)
    mutants: Callable[[str], Mapping[str, Mutant]] = lambda prim: {}
    #: every exercised vector bin has a configuration whose samples are all doc:
    pure: bool = True


class UnitGuards:
    """The guards every unit runs. Subclass as ``class TestUnit(UnitGuards): unit = U``;
    each guard is parametrized over the unit's primitives."""

    unit: ClassVar[Unit]  # not named Test*: pytest collects only the unit's subclass

    def pytest_generate_tests(self, metafunc: pytest.Metafunc) -> None:
        if "prim" in metafunc.fixturenames:
            metafunc.parametrize("prim", self.unit.prims)

    # helpers ------------------------------------------------------------------------
    def _doc(self, prim: str) -> dict:
        return yaml.safe_load((self.unit.group_dir / prim / "test.yaml").read_text())

    def _cases(self, prim: str) -> list[TestCase]:
        return cases(self.unit.root, self.unit.family, prim)

    # guards -------------------------------------------------------------------------
    def test_committed_files_are_current(self, prim: str) -> None:
        """Every file the generator renders exists and is current (flops review M5: a
        missing file fails; wrappers are rendered too, so none is hand-edited)."""
        d = self.unit.group_dir / prim
        for rel, text in self.unit.render(prim).items():
            path = d / rel
            assert path.is_file(), f"{path} missing: run the unit's generator"
            assert path.read_text() == text, f"{path} is stale: run the unit's generator"

    def test_validates_against_the_schema(self, prim: str) -> None:
        import jsonschema

        schema = json.loads((self.unit.root / "tools/xut/schemas/test.schema.json").read_text())
        doc = self._doc(prim)
        jsonschema.validate(doc, schema)
        assert doc["work_unit"] == self.unit.name
        for t in doc["tests"]:
            assert t["gaps"], t["id"]
            need = {r for r, v in t["runners"].items() if v != "yes"}
            assert need == set(t.get("unsupported_reasons", {})), t["id"]

    def test_every_generator_exists(self, prim: str) -> None:
        names = self.unit.generators(prim)
        for t in self._doc(prim)["tests"]:
            if t["style"] == "vector" and ":" in t["source"]:  # not a frozen .xvec
                assert t["source"].split(":", 1)[1] in names, t["id"]

    def test_exercises_are_reached(self, prim: str) -> None:
        """A vector test's exercises are reached by its own configurations (S23, S33)."""
        for case in self._cases(prim):
            if case.style != "vector":
                continue
            reached = set().union(*(r.reach.bins for r in _replayed(self.unit.root, case)))
            missing = set(case.exercises) - reached
            assert not missing, f"{case.id}: declared but never reached: {sorted(missing)}"

    def test_every_bin_is_exercised_or_a_gap(self, prim: str) -> None:
        from xut.lint import gap_bin
        from xut.status import coverage_bins

        prim_cases = self._cases(prim)
        named = {b for c in prim_cases for b in c.exercises}
        gaps = {gap_bin(g) for c in prim_cases for g in c.gaps}
        catalog_entry = catalog_model.load_entry(self.unit.family, prim, self.unit.root)
        missing = [b for b in coverage_bins(catalog_entry) if b not in named | gaps]
        assert not missing, missing

    def test_every_exercised_bin_has_a_pure_configuration(self, prim: str) -> None:
        """Every bin a vector test exercises is reached by at least one configuration
        of a test declaring it whose samples are all documented, so it is credited
        whatever an inferred detail turns out to be (rulings S44, S52; a failing
        configuration credits nothing). Status credits a bin only from the tests that
        declare it, so a pure configuration of another test does not count (S57.2)."""
        if not self.unit.pure:
            return
        vector = [c for c in self._cases(prim) if c.style == "vector"]
        declared = {b for v in vector for b in v.exercises}
        pure = {
            b
            for v in vector
            for r in _replayed(self.unit.root, v)
            if r.reach.pure
            for b in r.reach.bins & set(v.exercises)
        }
        missing = sorted(declared - pure)
        assert not missing, (
            f"only order- or inference-dependent configurations of the declaring tests "
            f"reach {missing}"
        )

    def test_every_credited_claim_has_a_failing_mutant(self, prim: str) -> None:
        """Ruling S55: a claim credits only where its rule decides a documented bit. Each
        claim a vector test exercises has a named mutant that breaks exactly that rule,
        and the mutant fails a documented bit in some configuration crediting the claim;
        for an event claim, in every one (S55a)."""
        from xut_models import registry

        vector = [c for c in self._cases(prim) if c.style == "vector"]
        claimed = sorted(
            {b.split(":", 1)[1] for v in vector for b in v.exercises if b.startswith("claim:")}
        )
        mutants = self.unit.mutants(prim)
        assert not set(claimed) - set(mutants), (
            f"no mutant for {sorted(set(claimed) - set(mutants))}"
        )
        golden = registry.get(self.unit.family, prim)
        for claim in claimed:
            spec = mutants[claim]
            mutant = spec.factory(golden)
            # a test credits only the claims it declares in exercises; a claim its model
            # reaches but it does not declare is exercise-only there (ruling S52)
            declaring = [v for v in vector if f"claim:{claim}" in v.exercises]
            verdicts = [
                mutant_fails(v, self.unit.root, claim, mutant, every=spec.event) for v in declaring
            ]
            crediting = [
                (v.id, ok) for v, ok in zip(declaring, verdicts, strict=True) if ok is not None
            ]
            assert crediting, f"{claim}: no configuration credits it"
            if spec.event:
                missed = [i for i, ok in crediting if not ok]
                assert not missed, (
                    f"{claim} (event): the mutant passes a crediting configuration of {missed}"
                )
            else:
                assert any(ok for _, ok in crediting), (
                    f"{claim}: the mutant passes every crediting configuration"
                )


@functools.cache
def _discovered(root: Path) -> tuple[TestCase, ...]:
    return tuple(discover(root))


def cases(root: Path, family: str, prim: str) -> list[TestCase]:
    """Every discovered test case of ``prim`` (discovery is cached per ``root``)."""
    return [c for c in _discovered(root) if c.family == family and c.prim == prim]


@functools.cache
def _replayed_cached(root: Path, case_id: str) -> tuple[_Replayed, ...]:
    case = next(c for c in _discovered(root) if c.id == case_id)
    return tuple(_replay_all(case, root))


def _replayed(root: Path, case: TestCase) -> tuple[_Replayed, ...]:
    return _replayed_cached(root, case.id)
