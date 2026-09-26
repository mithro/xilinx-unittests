# SPDX-License-Identifier: Apache-2.0
"""``xut verilatorize``: transform a model source's UNISIM models for Verilator (spec §6.2).

Every model file of ``ms.unisims`` (and ``ms.retarget``) is classified:

* ``unchanged``: no procedural ``assign``/``deassign``; Verilator uses the original;
* ``transformed``: analysed, rewritten and elaborated cleanly under every generate
  configuration; the copy is written to ``vz_dir(ms)/<MODEL>.v``;
* ``unsupported``: the transform refused it (``TransformError``); ``reason`` names the
  construct. The model is then ``verilator: unsupported``.

``vz_dir(ms)/manifest.json`` records every entry. A model is re-transformed only when its
incremental key changed (its source, glbl, the catalog-derived generate choices, or the
tool: every ``xut`` module the transform and the check are built from, ``tool_sources``),
or its transformed copy is missing. A re-transform resets its equivalence results.

``check=True`` then equivalence-checks (``xut.verilatorize.equiv.check_model``) every
transformed model under the default configuration and every one of its
``generate_configs``, recording ``pass``/``fail``/``error`` in ``equiv[config_key]`` and the
oracle in ``equiv_oracle[config_key]``; the work goes in
``vz_dir(ms)/equiv/<MODEL>/<config_dir>/``. A ``pass`` or ``fail`` is kept until the model
is re-transformed; a missing result or an ``error`` is (re)checked.
"""

from __future__ import annotations

import ast
import hashlib
import json
import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from xut import __version__
from xut.errors import XutError
from xut.modelsrc import ModelSource
from xut.paths import repo_root
from xut.verilatorize.analyze import (
    TransformError,
    analyze,
    generate_configs,
    has_procedural_assign,
)
from xut.verilatorize.rewrite import check_clean, rewrite, write_text

STATUSES = ("transformed", "unchanged", "unsupported")


@dataclass
class ModelEntry:
    status: str  # transformed | unchanged | unsupported
    source_sha256: str
    reason: str = ""
    triggers: list[str] = field(default_factory=list)
    enablers: list[str] = field(default_factory=list)
    forced: list[str] = field(default_factory=list)  # "X", or "HELPER.X" in a helper module
    generate_configs: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: config key ("default" or sorted "NAME=value,...") -> pass | fail | error (Task 14)
    equiv: dict[str, str] = field(default_factory=dict)
    #: config key -> the original model's oracle: iverilog | xsim ("" if it never ran)
    equiv_oracle: dict[str, str] = field(default_factory=dict)
    #: some override expression is not a constant: Icarus 12 evaluates such a procedural
    #: continuous assign once ("sorry"), so it cannot be the original's oracle (ruling S28b)
    nonconstant_overrides: bool = False
    xut_version: str = __version__
    # The rest of the incremental key (ruling S28c): the entry is redone when any changes.
    glbl_sha256: str = ""
    tool_sha256: str = ""  # tool_sources() + xut.__version__
    choices_sha256: str = ""  # the catalog-derived generate choices

    @classmethod
    def from_dict(cls, d: dict) -> ModelEntry:
        if d.get("status") not in STATUSES:
            raise XutError(f"manifest: bad model status {d.get('status')!r}")
        return cls(**d)


@dataclass
class Manifest:
    model_source: str
    models: dict[str, ModelEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        try:
            d = json.loads(Path(path).read_text())
            return cls(
                d["model_source"],
                {k: ModelEntry.from_dict(v) for k, v in d["models"].items()},
            )
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise XutError(f"cannot read verilatorize manifest {path}: {e}") from e

    def save(self, path: Path) -> None:
        d = {
            "model_source": self.model_source,
            "models": {k: asdict(v) for k, v in sorted(self.models.items())},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
        tmp.replace(path)


def vz_dir(ms: ModelSource) -> Path:
    """``build/verilatorized/<model-source>/`` (never committed)."""
    return repo_root() / "build" / "verilatorized" / ms.name


def model_files(ms: ModelSource) -> dict[str, Path]:
    """Model name -> file, UNISIM first (a retarget file never shadows a UNISIM one)."""
    out: dict[str, Path] = {}
    for d in ms.search:
        for f in sorted(d.glob("*.v")):
            out.setdefault(f.stem, f)
    return out


def catalog_choices(model: str) -> dict[str, list[str]] | None:
    """Verilog literals of the catalog's enumerated ``allowed`` values for ``model``'s
    attributes, or None when ``model`` is not a catalogued primitive. An attribute whose
    values do not all render as literals of its kind is left out (generate_configs then
    derives its candidates from the source)."""
    from xut.catalog.model import is_enumerated, load_entry
    from xut.workunits import load_family
    from xut.wrap import WrapError, render_attr

    root = repo_root()
    family = load_family(root)
    if not (root / "catalog" / family / f"{model}.yaml").is_file():
        return None
    entry = load_entry(family, model, root)
    out: dict[str, list[str]] = {}
    for a in entry.attributes:
        allowed = [str(v) for v in a.get("allowed") or []]
        if not is_enumerated(allowed):
            continue
        lits: list[str] = []
        try:
            for v in allowed:
                if a["kind"] == "bits" and v.isdigit():
                    lits.append(render_attr(a, int(v)))
                else:
                    lits.append(render_attr(a, v))
        except WrapError:
            continue
        out[a["name"]] = list(dict.fromkeys(lits))
    return out


def model_choices(path: Path, model: str) -> dict[str, list[str]] | None:
    """Generate-configuration candidates for ``model``: the catalog's allowed values, plus
    every value the source-derived configurations use for the same parameter. The catalog
    alone can leave a branch unelaborated (BUFR and FIFO18E1 test ``SIM_DEVICE`` against
    other families, while UG953 allows only ``"7SERIES"``), and ``analyze`` refuses any
    unelaborated branch; the union elaborates every branch and every catalogued value."""
    choices = catalog_choices(model)
    if not choices:
        return choices
    try:
        derived = generate_configs(path, model, None)
    except TransformError:
        derived = []  # the catalog may supply what the source alone cannot
    for cfg in derived:
        for name, value in cfg.items():
            if name in choices and value not in choices[name]:
                choices[name].append(value)
    return choices


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _xut_file(name: str) -> Path | None:
    """The source file of module ``name`` (``xut...``), or None if it is not a module."""
    base = Path(__file__).resolve().parent.parent.parent.joinpath(*name.split("."))
    for f in (base.with_suffix(".py"), base / "__init__.py"):
        if f.is_file():
            return f
    return None


def _xut_imports(f: Path) -> set[str]:
    """Every ``xut`` module ``f`` imports, at any depth of the file (function-local
    imports included), with the packages on the way (their ``__init__`` runs too)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(f.read_bytes(), str(f))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        for n in names:
            parts = n.split(".")
            if parts[0] == "xut":
                out |= {".".join(parts[: i + 1]) for i in range(len(parts))}
    return out


def tool_sources() -> list[Path]:
    """The files a transform and its equivalence check depend on (review M1): every module
    of this package, every ``xut`` module they import, transitively, and the vector
    testbench the check runs."""
    from xut.stimcompile import TB

    here = Path(__file__).resolve().parent
    todo = sorted(here.glob("*.py"))
    seen: set[Path] = set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        todo += [p for n in sorted(_xut_imports(f)) if (p := _xut_file(n)) and p not in seen]
    return [*sorted(seen), TB]


def tool_sha256() -> str:
    """Hash of ``tool_sources()`` (names and contents) and ``xut.__version__``."""
    h = hashlib.sha256(__version__.encode())
    root = Path(__file__).resolve().parent.parent.parent
    for f in tool_sources():
        h.update(str(f.relative_to(root) if f.is_relative_to(root) else f).encode() + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()


def choices_sha256(model: str) -> str:
    return hashlib.sha256(json.dumps(catalog_choices(model), sort_keys=True).encode()).hexdigest()


def _key(model: str, path: Path, glbl_sha: str, tool_sha: str) -> dict[str, str]:
    return {
        "source_sha256": _sha256(path),
        "glbl_sha256": glbl_sha,
        "tool_sha256": tool_sha,
        "choices_sha256": choices_sha256(model),
        "xut_version": __version__,
    }


def transform_one(path: Path, glbl: Path, out_dir: Path) -> ModelEntry:
    """Classify, and if forced, transform one model file (runs in a worker process)."""
    path = Path(path)
    sha = _sha256(path)
    out = Path(out_dir) / path.name
    if out.resolve() == path.resolve():
        raise XutError(f"{path}: the transformed copy would overwrite the model source")
    out.unlink(missing_ok=True)  # a crash below must not leave a stale copy behind
    if not has_procedural_assign(path):
        return ModelEntry("unchanged", sha)
    model = path.stem
    choices = model_choices(path, model)
    configs: list[dict[str, str]] = []
    try:
        configs = generate_configs(path, model, choices)
        an = analyze(path, model, glbl, choices)
        text = rewrite(an)
        check_clean(text, model, glbl, configs)
    except TransformError as e:
        return ModelEntry("unsupported", sha, reason=str(e), generate_configs=configs)
    write_text(out, text)
    forced = [*an.forced, *(f"{n}.{x}" for n, sub in an.submodules.items() for x in sub.forced)]
    return ModelEntry(
        "transformed",
        sha,
        triggers=an.triggers,
        enablers=an.enablers,
        forced=forced,
        generate_configs=configs,
        notes=an.notes,
        nonconstant_overrides=an.nonconstant_overrides,
    )


def _current(e: ModelEntry | None, key: dict[str, str], out: Path) -> bool:
    return (
        e is not None
        and all(getattr(e, k) == v for k, v in key.items())
        and (e.status != "transformed" or out.is_file())
    )


def verilatorize(
    ms: ModelSource,
    models: list[str] | None = None,
    *,
    jobs: int = 1,
    progress: Callable[[str], None] = print,
    check: bool = False,
) -> Manifest:
    """Transform ``ms``'s models (all, or ``models``) into ``vz_dir(ms)``, incrementally, and
    save ``vz_dir(ms)/manifest.json``. Prints ``progress: done=N total=M elapsed_s=E``, a
    last line with ``done=M`` even when a model crashed. ``check``: equivalence-check them
    too (module docstring), printing ``progress: equiv done=N total=M elapsed_s=E``."""
    files = model_files(ms)
    if models:
        unknown = sorted(set(models) - set(files))
        if unknown:
            raise XutError(f"no such model(s) in {ms.name}: {unknown}")
        files = {m: files[m] for m in sorted(set(models))}
    out_dir = vz_dir(ms)
    out_dir.mkdir(parents=True, exist_ok=True)
    mpath = out_dir / "manifest.json"
    man = Manifest.load(mpath) if mpath.is_file() else Manifest(ms.name)
    if man.model_source != ms.name:
        raise XutError(f"{mpath} belongs to model source {man.model_source}, not {ms.name}")
    glbl_sha, tool_sha = _sha256(ms.glbl), tool_sha256()
    keys = {m: _key(m, f, glbl_sha, tool_sha) for m, f in files.items()}
    todo = [
        (m, f)
        for m, f in files.items()
        if not _current(man.models.get(m), keys[m], out_dir / f.name)
    ]
    total, done, t0 = len(todo), 0, time.monotonic()
    progress(f"progress: done=0 total={total} elapsed_s=0")
    crash: XutError | None = None
    try:
        # forkserver: the caller may be multi-threaded (pytest-xdist, runner threads)
        ctx = multiprocessing.get_context("forkserver")
        with ProcessPoolExecutor(max_workers=max(1, jobs), mp_context=ctx) as ex:
            futs = {ex.submit(transform_one, f, ms.glbl, out_dir): m for m, f in todo}
            for fut in as_completed(futs):
                m = futs[fut]
                try:
                    entry = fut.result()  # a fresh entry: equiv results reset
                except Exception as e:  # a bug, not a refusal: record the others, then stop
                    man.models.pop(m, None)  # never keep a stale entry for a crashed model
                    if crash is None:
                        crash = XutError(f"{m}: verilatorize crashed: {type(e).__name__}: {e}")
                        crash.__cause__ = e
                else:
                    for k, v in keys[m].items():
                        setattr(entry, k, v)
                    man.models[m] = entry
                done += 1  # a crashed model is done too: the last line still reads done=M
                progress(
                    f"progress: done={done} total={total} elapsed_s={time.monotonic() - t0:.0f}"
                )
    finally:
        man.save(mpath)
    if crash is not None:
        raise crash
    if check:
        try:
            _check_all(ms, man, sorted(files), out_dir, jobs, progress)
        finally:
            man.save(mpath)
    return man


def _check_all(
    ms: ModelSource,
    man: Manifest,
    models: list[str],
    out_dir: Path,
    jobs: int,
    progress: Callable[[str], None],
) -> None:
    """Equivalence-check every configuration of ``models`` that has no pass/fail yet."""
    from xut.verilatorize.equiv import Checked, check_model, config_dir, config_key

    todo: list[tuple[str, dict[str, str]]] = []
    for m in models:
        e = man.models.get(m)
        if e is None or e.status != "transformed":
            continue
        for cfg in e.generate_configs or [{}]:
            if e.equiv.get(config_key(cfg)) not in ("pass", "fail"):
                todo.append((m, cfg))
    files = model_files(ms)
    total, done, t0 = len(todo), 0, time.monotonic()
    progress(f"progress: equiv done=0 total={total} elapsed_s=0")
    # threads: each check waits on its simulator subprocesses
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = {}
        for m, cfg in todo:
            e = man.models[m]
            subject = Checked(m, files[m], e.triggers, e.enablers, e.nonconstant_overrides)
            work = out_dir / "equiv" / m / config_dir(config_key(cfg))
            futs[pool.submit(check_model, subject, ms, work, cfg, lib=out_dir)] = m
        for fut in as_completed(futs):
            r = fut.result()  # check_model returns an error result, it does not raise
            e = man.models[futs[fut]]
            e.equiv[r.config], e.equiv_oracle[r.config] = r.status, r.oracle
            done += 1
            progress(
                f"progress: equiv done={done} total={total} elapsed_s={time.monotonic() - t0:.0f}"
            )
