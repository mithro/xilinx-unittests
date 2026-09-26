# SPDX-License-Identifier: Apache-2.0
"""``xut verilatorize``: transform a model source's UNISIM models for Verilator (spec §6.2).

Every model file of ``ms.unisims`` (and ``ms.retarget``) is classified:

* ``unchanged``: neither rewrite applies; Verilator uses the original;
* ``transformed``: rewritten and elaborated cleanly under every generate configuration;
  the copy is written to ``vz_dir(ms)/<MODEL>.v``. ``rewrites`` names what was applied:
  ``shadow`` (procedural ``assign``/``deassign``, the shadow-register transform) and/or
  ``zcmp`` (``xut.verilatorize.zcmp``: an input port compared with z, ruling S38). A model
  that needs only the z-compare rewrite is ``transformed`` too;
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
is re-transformed or the simulators change (``sim_tools``: the Icarus version and image,
the xsim version); a missing result or an ``error`` is (re)checked.

**Hierarchies** (ruling S45). Each entry records the models its file ``instantiates``.
``verilatorize`` of some models also transforms every model their hierarchy reaches, so a
copy in ``vz_dir`` is never used stale or missing, and its contents never depend on which
models were asked for first (the union of closures). ``_link`` then records, per model,
the models of its hierarchy that are ``transformed`` (``depends_on_transformed``) or
``unsupported`` (``depends_on_unsupported``), the union of the rewrites it runs under
(``effective_rewrites``) and a hash of its transformed dependencies (``deps_sha256``); a
change of that hash discards the model's equivalence verdicts. A model with a transformed
dependency is *gated* like a transformed one: its equivalence check runs the original
hierarchy against the vz hierarchy (``checked``), and ``--check`` checks it too.

``ensure_model`` is the runners' entry point (the ``verilator`` runner and its
``iverilog-vz`` companion, Task 15): it transforms one model on demand and runs the
equivalence check for one configuration when the manifest has no result for it.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import multiprocessing
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from xut import __version__
from xut.errors import XutError
from xut.modelsrc import ModelSource
from xut.paths import repo_root
from xut.verilatorize import zcmp
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
    #: config key -> the simulators the result was computed with (``sim_tools``): a kept
    #: pass/fail is rechecked when they change
    equiv_tools: dict[str, str] = field(default_factory=dict)
    #: config key -> the check's reason (why it is an error or a fail; "" for a pass)
    equiv_reason: dict[str, str] = field(default_factory=dict)
    #: the rewrites applied: "shadow" and/or "zcmp" (ruling S38); empty unless transformed
    rewrites: list[str] = field(default_factory=list)
    #: models of this source the file instantiates (its own helper modules excluded)
    instantiates: list[str] = field(default_factory=list)
    #: models of its hierarchy (transitively) that are transformed / unsupported (S45)
    depends_on_transformed: list[str] = field(default_factory=list)
    depends_on_unsupported: list[str] = field(default_factory=list)
    #: its own rewrites and those of depends_on_transformed
    effective_rewrites: list[str] = field(default_factory=list)
    #: hash of depends_on_transformed and their keys: a change discards the verdicts
    deps_sha256: str = ""
    #: some override expression is not a constant: Icarus 12 evaluates such a procedural
    #: continuous assign once ("sorry"), so it cannot be the original's oracle (ruling S28b)
    nonconstant_overrides: bool = False
    xut_version: str = __version__
    # The rest of the incremental key (ruling S28c): the entry is redone when any changes.
    glbl_sha256: str = ""
    tool_sha256: str = ""  # tool_sources() + xut.__version__
    choices_sha256: str = ""  # the catalog-derived generate choices

    @property
    def gated(self) -> bool:
        """Verilator results need an equivalence verdict: the model is transformed, or its
        hierarchy holds a transformed model (ruling S45)."""
        return self.status == "transformed" or bool(self.depends_on_transformed)

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


def vz_dir(ms: ModelSource, root: Path | None = None) -> Path:
    """``<root>/build/verilatorized/<model-source>/`` (never committed); ``root`` defaults to
    the repository (a runner passes its run root, ``RunContext.root``)."""
    return (root if root is not None else repo_root()) / "build" / "verilatorized" / ms.name


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


def instantiated(path: Path) -> list[str]:
    """The modules ``path`` instantiates that it does not define (syntax only, every
    generate branch), ``glbl`` excluded."""
    import pyslang

    from xut.verilatorize.analyze import _walk_syntax

    kind = pyslang.syntax.SyntaxKind
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    defined: set[str] = set()
    used: set[str] = set()
    for n in _walk_syntax(tree.root):
        if n.kind == kind.ModuleDeclaration:
            defined.add(n.header.name.valueText)
        elif n.kind == kind.HierarchyInstantiation:
            used.add(n.type.valueText)
    return sorted(used - defined - {"glbl"})


def hierarchy(ms: ModelSource, models: list[str]) -> list[str]:
    """``models`` and every model of ``ms`` their files reach by instantiation."""
    files = model_files(ms)
    seen: list[str] = []
    todo = list(models)
    while todo:
        m = todo.pop(0)
        if m in seen or m not in files:
            continue
        seen.append(m)
        todo += instantiated(files[m])
    return seen


def transform_one(path: Path, glbl: Path, out_dir: Path) -> ModelEntry:
    """Classify, and if needed, transform one model file (runs in a worker process); the
    entry records what the file instantiates."""
    entry = _transform_one(Path(path), glbl, out_dir)
    entry.instantiates = instantiated(Path(path))
    return entry


def _transform_one(path: Path, glbl: Path, out_dir: Path) -> ModelEntry:
    path = Path(path)
    sha = _sha256(path)
    out = Path(out_dir) / path.name
    if out.resolve() == path.resolve():
        raise XutError(f"{path}: the transformed copy would overwrite the model source")
    out.unlink(missing_ok=True)  # a crash below must not leave a stale copy behind
    model = path.stem
    forced_regs = has_procedural_assign(path)
    try:
        zs = zcmp.find(path, model)
    except TransformError as e:
        return ModelEntry("unsupported", sha, reason=str(e))
    if not forced_regs and not zs:
        return ModelEntry("unchanged", sha)
    choices = model_choices(path, model)
    configs: list[dict[str, str]] = []
    notes: list[str] = []
    rewrites: list[str] = []
    an = None
    try:
        if forced_regs:
            configs = generate_configs(path, model, choices)
            an = analyze(path, model, glbl, choices)
            text = rewrite(an)
            rewrites.append("shadow")
            notes += an.notes
        else:
            text = path.read_bytes().decode("utf-8", "surrogateescape")
            try:
                configs = generate_configs(path, model, choices)
            except TransformError as e:  # recorded: only the z-compare rewrite needs none
                notes.append(
                    f"no generate configurations derived ({e}); the equivalence check covers "
                    "the default configuration and each test configuration on demand"
                )
        text, found = zcmp.rewrite_text(text, model)
        if found:
            rewrites.append(zcmp.REWRITE)
            ports = sorted({z.port for z in found})
            notes.append(
                f"z-compare rewrite (ruling S38): {len(found)} comparison(s) of input "
                f"port(s) {', '.join(ports)}; valid only with every input driven"
            )
        if left := zcmp.leftover(text):
            notes.append(
                f"{left} z-literal comparison(s) remain in preprocessor-disabled code "
                "(e.g. `ifdef XIL_TIMING); Verilator refuses them if that code is enabled"
            )
        check_clean(text, model, glbl, configs)
    except TransformError as e:
        return ModelEntry("unsupported", sha, reason=str(e), generate_configs=configs)
    write_text(out, text)
    if an is None:
        return ModelEntry(
            "transformed", sha, generate_configs=configs, notes=notes, rewrites=rewrites
        )
    forced = [*an.forced, *(f"{n}.{x}" for n, sub in an.submodules.items() for x in sub.forced)]
    return ModelEntry(
        "transformed",
        sha,
        triggers=an.triggers,
        enablers=an.enablers,
        forced=forced,
        generate_configs=configs,
        notes=notes,
        nonconstant_overrides=an.nonconstant_overrides,
        rewrites=rewrites,
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
    out_dir: Path | None = None,
) -> Manifest:
    """Transform ``ms``'s models (all, or ``models``) into ``out_dir`` (default
    ``vz_dir(ms)``), incrementally, and save ``out_dir/manifest.json``. Prints
    ``progress: done=N total=M elapsed_s=E``, a last line with ``done=M`` even when a
    model crashed. ``check``: equivalence-check them
    too (module docstring), printing ``progress: equiv done=N total=M elapsed_s=E``."""
    files = model_files(ms)
    if models:
        unknown = sorted(set(models) - set(files))
        if unknown:
            raise XutError(f"no such model(s) in {ms.name}: {unknown}")
        files = {m: files[m] for m in sorted(hierarchy(ms, sorted(set(models))))}
    out_dir = Path(out_dir) if out_dir is not None else vz_dir(ms)
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
        _link(man)
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


def _link(man: Manifest) -> None:
    """Record every entry's hierarchy facts (module docstring): ``depends_on_transformed``,
    ``depends_on_unsupported``, ``effective_rewrites`` and ``deps_sha256``; a changed
    ``deps_sha256`` discards the entry's verdicts."""
    for e in man.models.values():
        seen: set[str] = set()
        todo = list(e.instantiates)
        while todo:
            d = todo.pop()
            if d in seen or d not in man.models:  # not a model of this source (secureip)
                continue
            seen.add(d)
            todo += man.models[d].instantiates
        dt = sorted(d for d in seen if man.models[d].status == "transformed")
        e.depends_on_transformed = dt
        e.depends_on_unsupported = sorted(d for d in seen if man.models[d].status == "unsupported")
        e.effective_rewrites = sorted(set(e.rewrites).union(*(man.models[d].rewrites for d in dt)))
        key = [[d, *(getattr(man.models[d], k) for k in _DEP_KEY)] for d in dt]
        sha = hashlib.sha256(json.dumps(key).encode()).hexdigest()
        if e.deps_sha256 != sha:
            e.deps_sha256 = sha
            for verdicts in (e.equiv, e.equiv_oracle, e.equiv_reason, e.equiv_tools):
                verdicts.clear()


_DEP_KEY = ("source_sha256", "glbl_sha256", "tool_sha256", "choices_sha256", "xut_version")


def checked(man: Manifest, model: str, files: dict[str, Path]) -> object:
    """The equivalence subject (``equiv.Checked``) of a gated ``model``: its original file
    against its vz hierarchy, whose copies (its own when it is transformed, and every
    transformed dependency's) are compiled explicitly (``lib_models``). Its triggers add the
    dependencies' ``glbl.*`` triggers (their port triggers are not the model's ports)."""
    from xut.verilatorize.equiv import Checked

    e = man.models[model]
    deps = [man.models[d] for d in e.depends_on_transformed]
    glbl = sorted({t for d in deps for t in d.triggers if t.startswith("glbl.")} - set(e.triggers))
    own = (model,) if e.status == "transformed" else ()
    return Checked(
        model,
        files[model],
        [*e.triggers, *glbl],
        list(e.enablers),
        e.nonconstant_overrides or any(d.nonconstant_overrides for d in deps),
        tuple(e.effective_rewrites or e.rewrites),
        own + tuple(e.depends_on_transformed),
    )


def sim_tools(ms: ModelSource, work: Path) -> str:
    """The simulators an equivalence result depends on, as one JSON string: the Icarus
    version and the xut-sim image ID (or ``native``), and the xsim version (or why it is
    unavailable). Part of the redo key of a kept verdict."""
    from xut.container import executor_for, image_digest, sim_tool_versions
    from xut.runners import xsim

    work.mkdir(parents=True, exist_ok=True)
    parts: dict[str, str] = {}
    try:
        ex = executor_for(ms, work)
        parts["iverilog"] = sim_tool_versions(ex, work)["iverilog"]
        image = getattr(ex, "image", None)
        parts["image"] = (image_digest(image) or "missing") if image else "native"
    except Exception as e:  # recorded: every check then errors, and is redone later
        parts["iverilog"] = f"unavailable: {type(e).__name__}: {e}"
    if not xsim.settings_available():
        parts["xsim"] = "unavailable"
    else:
        try:
            parts["xsim"] = xsim.xsim_version(work)
        except Exception as e:
            parts["xsim"] = f"unavailable: {type(e).__name__}: {e}"
    return json.dumps(parts, sort_keys=True)


def _check_all(
    ms: ModelSource,
    man: Manifest,
    models: list[str],
    out_dir: Path,
    jobs: int,
    progress: Callable[[str], None],
) -> None:
    """Equivalence-check every configuration of the gated ``models`` (a model with an
    unsupported dependency is not: its results are refused anyway) that has no current
    pass/fail yet. Configurations are keyed canonically (``model_attrs``)."""
    from xut.verilatorize.equiv import check_model, config_dir, config_key

    tools = sim_tools(ms, out_dir / "equiv")
    todo: list[tuple[str, dict[str, str]]] = []
    for m in models:
        e = man.models.get(m)
        if e is None or not e.gated or e.depends_on_unsupported:
            continue
        cfgs = {config_key(c): c for c in (model_attrs(ms, m, c) for c in e.generate_configs)}
        for k, cfg in ({"default": {}} | cfgs).items():
            if e.equiv.get(k) not in ("pass", "fail") or e.equiv_tools.get(k) != tools:
                todo.append((m, cfg))
    files = model_files(ms)
    total, done, t0 = len(todo), 0, time.monotonic()
    progress(f"progress: equiv done=0 total={total} elapsed_s=0")
    # threads: each check waits on its simulator subprocesses
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = {}
        for m, cfg in todo:
            subject = checked(man, m, files)
            work = out_dir / "equiv" / m / config_dir(config_key(cfg))
            futs[pool.submit(check_model, subject, ms, work, cfg, lib=out_dir)] = m
        for fut in as_completed(futs):
            r = fut.result()  # check_model returns an error result, it never raises
            e = man.models[futs[fut]]
            e.equiv[r.config], e.equiv_oracle[r.config] = r.status, r.oracle
            e.equiv_reason[r.config] = r.reason
            e.equiv_tools[r.config] = tools
            done += 1
            progress(
                f"progress: equiv done={done} total={total} elapsed_s={time.monotonic() - t0:.0f}"
            )


# ---- on demand, for the runners (Task 15) --------------------------------------------------
#: One lock per (transform directory, model): runner jobs are threads, and two runners (or
#: two configurations) of one model must not transform or check it twice at once.
_MODEL_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
#: ``manifest.json`` is read, changed and written whole: one writer at a time per process.
_MANIFEST_LOCK = threading.Lock()
#: (transform directory, model) -> its entry, once this process has made sure it is current.
_ENTRIES: dict[tuple[str, str], ModelEntry] = {}
#: transform directory -> ``sim_tools`` for it (computed once per process: xsim is slow)
_TOOLS: dict[str, str] = {}
#: (transform directory, model, config key) checked by this process: never checked twice
_CHECKED: set[tuple[str, str, str]] = set()


def _model_lock(key: tuple[str, str]) -> threading.Lock:
    with _LOCKS_GUARD:
        return _MODEL_LOCKS.setdefault(key, threading.Lock())


def _sim_tools(ms: ModelSource, out: Path) -> str:
    with _LOCKS_GUARD:
        lock = _MODEL_LOCKS.setdefault((str(out), "\0tools"), threading.Lock())
    with lock:
        if str(out) not in _TOOLS:
            _TOOLS[str(out)] = sim_tools(ms, out / "equiv")
        return _TOOLS[str(out)]


def undriven_inputs(ms: ModelSource, model: str, connected: dict[str, int]) -> list[str]:
    """The input ports of ``model`` (its HDL) not fully driven: absent from ``connected``
    (port -> bits driven), or with fewer bits driven than the port has (review M3). A
    wrapper leaving one undriven breaks the z-compare rewrite's validity condition (S38)."""
    out = []
    for p in parsed(ms, model).ports:
        n = connected.get(p.name, 0)
        if p.direction == "input" and n < p.width:
            out.append(p.name if n == 0 else f"{p.name} ({n} of {p.width} bits)")
    return sorted(out)


@functools.lru_cache(maxsize=256)
def _module(path: str, mtime_ns: int, model: str) -> object:
    from xut.catalog.unisim import parse_module

    return parse_module(Path(path), model)


def parsed(ms: ModelSource, model: str) -> object:
    """``parse_module`` of ``model``'s file, cached while the file is unchanged."""
    f = model_files(ms)[model]
    return _module(str(f), f.stat().st_mtime_ns, model)


def model_attrs(ms: ModelSource, model: str, attrs: dict | None) -> dict[str, str]:
    """``attrs`` as the equivalence check keys them (canonical): only the parameters
    ``model`` declares (an sv configuration may also set testbench parameters), each
    rendered as the Verilog literal of its kind (``0`` and ``"1'b0"`` are one configuration
    of a 1-bit attribute), without those equal to the parameter's default (FDRE's
    ``INIT=1'b0`` is the ``default`` configuration: review M5)."""
    from xut.wrap import WrapError, render_attr, spec_from_hdl

    if not attrs:
        return {}
    mod = parsed(ms, model)
    decl = {p.name: {"name": p.name, "kind": p.kind, "width": p.width} for p in mod.params}
    mine = {k: v for k, v in attrs.items() if k in decl}
    out = dict(spec_from_hdl(mod, "default", mine, raw_clock_out=True).attrs)
    for p in mod.params:
        if p.name not in out:
            continue
        try:
            default = render_attr(decl[p.name], p.default, allow_x=True)
        except WrapError:
            continue  # a default that is not a plain literal: keep the attribute
        if default == out[p.name]:
            del out[p.name]
    return out


def ensure_model(
    ms: ModelSource,
    model: str,
    attrs: dict | None = None,
    *,
    root: Path | None = None,
    log: Callable[[str], None] = print,
    check: bool = True,
) -> ModelEntry:
    """``model``'s manifest entry, transformed (on demand) into ``vz_dir(ms, root)`` and, if it
    is ``transformed``, equivalence-checked under ``attrs`` (``model_attrs``) when
    ``equiv[config_key]`` has no result yet; the verdict (and its reason) is recorded in the
    manifest. The entry is cached for the process; a per-model lock serialises the work, since
    runner jobs are threads. Only ``model`` is transformed here: any other model it
    instantiates is used as ``xut verilatorize`` last left it. A verdict is (re)checked by the
    rule of ``--check``: when it is missing, an ``error``, or was computed with other
    simulators (``equiv_tools`` differs from ``sim_tools``), at most once per process and
    configuration; the verdict is recorded with the ``sim_tools`` fingerprint. ``log``
    receives the driver's progress lines. The first call per process transforms the model's
    whole hierarchy (``verilatorize`` follows it), re-transforming any stale copy; a gated
    model (``ModelEntry.gated``: transformed, or over a transformed dependency) is checked,
    one with an unsupported dependency is not. ``check=False`` only transforms."""
    from xut.verilatorize.equiv import check_model, config_dir, config_key

    out = vz_dir(ms, root)
    key = (str(out), model)
    with _model_lock(key):
        e = _ENTRIES.get(key)
        if e is None:
            with _MANIFEST_LOCK:
                man = verilatorize(ms, [model], progress=log, out_dir=out)
            e = _ENTRIES[key] = man.models[model]
        if not check or not e.gated or e.status == "unsupported" or e.depends_on_unsupported:
            return e
        cfg = model_attrs(ms, model, attrs)
        k = config_key(cfg)
        if (str(out), model, k) in _CHECKED:
            return e
        tools = _sim_tools(ms, out)
        if e.equiv.get(k) in ("pass", "fail") and e.equiv_tools.get(k) == tools:
            return e
        with _MANIFEST_LOCK:
            subject = checked(Manifest.load(out / "manifest.json"), model, model_files(ms))
        why = "no verdict" if k not in e.equiv else f"was {e.equiv[k]}, or other simulators"
        log(f"equiv: checking {model} [{k}] ({why})")
        r = check_model(subject, ms, out / "equiv" / model / config_dir(k), cfg, lib=out)
        log(f"equiv: {r.status}: {model} [{k}] oracle={r.oracle or '-'} {r.reason}".rstrip())
        _CHECKED.add((str(out), model, k))
        e.equiv[k], e.equiv_oracle[k], e.equiv_reason[k] = r.status, r.oracle, r.reason
        e.equiv_tools[k] = tools
        with _MANIFEST_LOCK:
            mpath = out / "manifest.json"
            man = Manifest.load(mpath)
            cur = man.models.get(model)
            if cur is not None and (cur.source_sha256, cur.deps_sha256) == (
                e.source_sha256,
                e.deps_sha256,
            ):
                cur.equiv[k], cur.equiv_oracle[k] = r.status, r.oracle
                cur.equiv_reason[k], cur.equiv_tools[k] = r.reason, tools
                man.save(mpath)
            else:  # the manifest moved on (another process re-transformed): say so
                log(
                    f"equiv: {model} [{k}] {r.status} not recorded in {mpath}: its entry "
                    "changed since this process read it (review M5)"
                )
        return e
