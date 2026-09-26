# SPDX-License-Identifier: Apache-2.0
"""``xut verilatorize``: transform a model source's UNISIM models for Verilator (spec §6.2).

Every model file of ``ms.unisims`` (and ``ms.retarget``) is classified:

* ``unchanged``: no procedural ``assign``/``deassign``; Verilator uses the original;
* ``transformed``: analysed, rewritten and elaborated cleanly under every generate
  configuration; the copy is written to ``vz_dir(ms)/<MODEL>.v``;
* ``unsupported``: the transform refused it (``TransformError``); ``reason`` names the
  construct. The model is then ``verilator: unsupported``.

``vz_dir(ms)/manifest.json`` records every entry. A model is re-transformed only when its
source sha256 or ``xut.__version__`` changed (or its transformed copy is missing).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
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
    xut_version: str = __version__

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


def transform_one(path: Path, glbl: Path, out_dir: Path) -> ModelEntry:
    """Classify, and if forced, transform one model file (runs in a worker process)."""
    path = Path(path)
    sha = _sha256(path)
    out = Path(out_dir) / path.name
    if not has_procedural_assign(path):
        out.unlink(missing_ok=True)
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
        out.unlink(missing_ok=True)
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
    )


def _current(e: ModelEntry | None, sha: str, out: Path) -> bool:
    return (
        e is not None
        and e.source_sha256 == sha
        and e.xut_version == __version__
        and (e.status != "transformed" or out.is_file())
    )


def verilatorize(
    ms: ModelSource,
    models: list[str] | None = None,
    *,
    jobs: int = 1,
    progress: Callable[[str], None] = print,
) -> Manifest:
    """Transform ``ms``'s models (all, or ``models``) into ``vz_dir(ms)``, incrementally, and
    save ``vz_dir(ms)/manifest.json``. Prints ``progress: done=N total=M elapsed_s=E``."""
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
    todo = [
        (m, f)
        for m, f in files.items()
        if not _current(man.models.get(m), _sha256(f), out_dir / f.name)
    ]
    total, done, t0 = len(todo), 0, time.monotonic()
    progress(f"progress: done=0 total={total} elapsed_s=0")
    try:
        with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = {ex.submit(transform_one, f, ms.glbl, out_dir): m for m, f in todo}
            for fut in as_completed(futs):
                m = futs[fut]
                try:
                    man.models[m] = fut.result()  # a fresh entry: equiv results reset
                except TransformError:
                    raise
                except Exception as e:  # a bug, not a refusal: stop, naming the model
                    raise XutError(f"{m}: verilatorize crashed: {type(e).__name__}: {e}") from e
                done += 1
                progress(
                    f"progress: done={done} total={total} elapsed_s={time.monotonic() - t0:.0f}"
                )
    finally:
        man.save(mpath)
    return man
