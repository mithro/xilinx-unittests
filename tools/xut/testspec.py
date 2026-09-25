# SPDX-License-Identifier: Apache-2.0
"""Test discovery: every test of every ``tests/<family>/<group>/<PRIM>/test.yaml`` (spec §11).

Each file is validated against ``test.schema.json`` before any of it is used; an invalid
file or a duplicated test id is a ``ConfigError`` (a clean CLI error), never a test
that silently drops out of the run.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

from xut.errors import ConfigError
from xut.schemas import validate as validate_schema

#: The runners every test declares in ``runners`` (spec §6): lint warns about a missing
#: one, which ``declared`` treats as ``"no"`` with the reason ``not declared``.
DECLARED_RUNNERS = ("python", "xsim", "iverilog", "verilator", "hw")
#: Runners whose declaration is inherited from another: ``iverilog-vz`` only exists to
#: guard the Verilator results, so it runs exactly where ``verilator`` does.
DECLARATION_OF = {"iverilog-vz": "verilator"}


@dataclass(frozen=True)
class TestCase:
    """One entry of a ``test.yaml`` ``tests:`` list, with its file's context."""

    __test__ = False  # not a pytest test class, despite the name

    id: str
    family: str
    prim: str
    level: str
    style: str
    source: str | None  # as written in test.yaml, relative to test_dir
    test_dir: Path
    runners: dict[str, str]
    unsupported_reasons: dict[str, str] = field(default_factory=dict)
    config_exclusions: dict[str, dict[str, str]] = field(default_factory=dict)
    flows: list[str] = field(default_factory=list)
    exercises: list[str] = field(default_factory=list)
    attr_sampling: dict[str, list] = field(default_factory=dict)
    related: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    expected_divergence: list[dict] = field(default_factory=list)
    configs: list[dict] = field(default_factory=list)
    timeout_s: int | None = None
    sv_deviations: list[str] = field(default_factory=list)
    work_unit: str = ""

    @property
    def group(self) -> str:
        """The ``<group>`` directory: ``tests/<family>/<group>/<PRIM>``."""
        return self.test_dir.parent.name

    @property
    def shared_dirs(self) -> list[Path]:
        """Directories put on the generator / testbench search path: the work unit's
        shared test code, ``tests/<family>/<group>/_shared/<work_unit>``, when that
        directory exists (``xut.workunits.owned_paths`` gives it to the unit)."""
        d = self.test_dir.parent / "_shared" / self.work_unit
        return [d] if self.work_unit and d.is_dir() else []


def _cases_of(path: Path, data: dict) -> list[TestCase]:
    out = []
    for t in data["tests"]:
        out.append(
            TestCase(
                id=t["id"],
                family=data["family"],
                prim=data["primitive"],
                level=t["level"],
                style=t["style"],
                source=t.get("source"),
                test_dir=path.parent,
                runners=dict(t["runners"]),
                unsupported_reasons=dict(t.get("unsupported_reasons", {})),
                config_exclusions={r: dict(g) for r, g in t.get("config_exclusions", {}).items()},
                flows=list(t["flows"]),
                exercises=list(t["exercises"]),
                attr_sampling=dict(t["attr_sampling"]),
                related=list(t.get("related", [])),
                gaps=list(t.get("gaps", [])),
                expected_divergence=list(t.get("expected_divergence", [])),
                configs=[dict(c) for c in t.get("configs", [])],
                timeout_s=t.get("timeout_s"),
                sv_deviations=list(t.get("sv_deviations", [])),
                work_unit=data["work_unit"],
            )
        )
    return out


def discover(root: Path) -> list[TestCase]:
    """Every test under ``<root>/tests``, in file-path order then file order."""
    root = Path(root)
    cases: list[TestCase] = []
    where: dict[str, Path] = {}
    for f in sorted((root / "tests").glob("**/test.yaml")):
        rel = f.relative_to(root)
        try:
            data = yaml.safe_load(f.read_text())
            validate_schema(data, "test")
        except yaml.YAMLError as e:
            raise ConfigError(f"{rel}: invalid YAML: {str(e).splitlines()[0]}") from e
        except jsonschema.ValidationError as e:
            raise ConfigError(f"{rel}: {e.json_path}: {e.message}") from e
        for c in _cases_of(f, data):
            if c.id in where:
                raise ConfigError(
                    f"{rel}: test id {c.id} is also defined in {where[c.id].relative_to(root)}"
                )
            where[c.id] = f
            cases.append(c)
    return cases


def _matches(case: TestCase, pattern: str) -> bool:
    if pattern.startswith("unit:"):
        return case.work_unit == pattern.removeprefix("unit:")
    return case.prim == pattern or fnmatch.fnmatchcase(case.id, pattern)


def select(cases: list[TestCase], patterns: list[str]) -> list[TestCase]:
    """The cases matching any pattern: a test-id glob, a primitive name or ``unit:<name>``."""
    return [c for c in cases if any(_matches(c, p) for p in patterns)]


def declared(case: TestCase, runner: str) -> tuple[bool, str]:
    """``(True, "")`` if ``runner`` is declared ``"yes"`` for ``case``; otherwise
    ``(False, reason)``: the ``unsupported_reasons`` entry for ``"no"``/``"unsupported"``,
    or ``"not declared"`` when the runner is absent from ``runners``."""
    r = DECLARATION_OF.get(runner, runner)
    value = case.runners.get(r)
    if value is None:
        return False, "not declared"
    if value == "yes":
        return True, ""
    return False, case.unsupported_reasons.get(r, f'"{value}" without a reason')


def exclusions_for(case: TestCase, runner: str) -> dict[str, str]:
    """``{cfg glob: reason}`` excluded for ``runner``; ``iverilog-vz`` inherits
    ``verilator``'s exclusions exactly as it inherits its declaration."""
    return dict(case.config_exclusions.get(DECLARATION_OF.get(runner, runner), {}))


def prim_of(test_id: str) -> str:
    """``<family>.<PRIM>.<level>.<name>`` -> ``<PRIM>``."""
    return test_id.split(".")[1]


def finding_slug(cls: str, test_id: str) -> str:
    """``<cls>-<level>-<name>``, dots in the name as ``-`` (spec §8 "Recording")."""
    return f"{cls}-{test_id.split('.', 2)[2].replace('.', '-')}"


def finding_id(prim: str, cls: str, test_id: str) -> str:
    """The id (``findings/<id>.md`` stem) of a ``cls`` finding of ``test_id``: the one
    name an ``expected_divergence`` entry for it may use (ruling S17)."""
    return f"{prim}-{finding_slug(cls, test_id)}"
