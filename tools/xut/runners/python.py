# SPDX-License-Identifier: Apache-2.0
"""The ``python`` runner: stimulus generation and golden-model expected traces.

For a vector test it imports the generator named by ``source`` (or loads a frozen
``.xvec``), and for every configuration writes ``cfg-<cfg>/dut/`` (the wrapper),
``stim.xvec`` (validated and marked for hw renderability) and ``expected.xtr`` (the
golden replay; header-only for ``expect=reject``). ``configs.json`` lists every
configuration generated, errored ones included: the other runners read their
configuration list, stimuli and expectations from this directory (review #10).

- An invalid stimulus is a generator bug: ``error``.
- No golden model for the primitive, or a stimulus the model does not describe
  (``ModelUnsupported``): ``skip`` with the reason. The other runners then report
  ``error "no expected trace (python: skip: ...)"`` for that configuration.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

from xut.errors import XutError
from xut.formats import xtr, xvec
from xut.formats.common import is_cfg
from xut.formats.xvec import Vec
from xut.golden import InvalidStimulus, polarity_bins, replay
from xut.runners.base import (
    ConfigResult,
    RunContext,
    Runner,
    RunResult,
    seed_for,
    sha256_file,
    timeout_for,
    workdir,
)
from xut.stimgen import GenContext
from xut.testspec import TestCase
from xut.validate import mark, validate
from xut.wrap import DutSpec, spec_from_catalog, write_dut
from xut_models import registry
from xut_models.base import ModelContractError, ModelUnsupported


class SourceError(XutError, ValueError):
    """A vector test's ``source`` cannot be used."""


class PythonTimeout(XutError, TimeoutError):
    """The generator or the golden model exceeded the test's timeout."""


def _watchdog[T](fn: Callable[[], T], deadline: float, what: str, limit_s: int) -> T:
    """``fn()`` in a daemon thread, abandoned with ``PythonTimeout`` at ``deadline``
    (time.monotonic). A Python thread cannot be killed: a runaway generator keeps
    spinning in the background, but the run reports ``error`` and moves on. Once the
    deadline has passed no new thread is started (after one golden-model timeout the
    remaining configurations time out at once instead of each leaving a runaway)."""
    if time.monotonic() >= deadline:  # never start work once the deadline has passed
        raise PythonTimeout(f"timeout: {what} exceeded the {limit_s} s limit")
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # re-raised in the caller's thread
            box["error"] = e

    t = threading.Thread(target=target, name=f"xut-python-{what}", daemon=True)
    t.start()
    t.join(max(0.0, deadline - time.monotonic()))
    if t.is_alive():
        raise PythonTimeout(f"timeout: {what} exceeded the {limit_s} s limit")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


@contextmanager
def _on_path(dirs: list[Path]) -> Iterator[None]:
    added = [str(d) for d in dirs if str(d) not in sys.path]
    sys.path[:0] = added
    try:
        yield
    finally:
        for d in added:
            sys.path.remove(d)


def _import_generator(case: TestCase, spec: str) -> Callable[[GenContext], Iterator[Vec]]:
    file, _, func = spec.partition(":")
    path = case.test_dir / file
    if not func or not path.is_file():
        raise SourceError(
            f"{case.id}: source {spec!r} must be vectors/<file>.py:<function> naming an "
            f"existing file (looked for {path})"
        )
    modname = "xut_gen_" + "".join(ch if ch.isalnum() else "_" for ch in f"{case.id}_{file}")
    mspec = importlib.util.spec_from_file_location(modname, path)
    if mspec is None or mspec.loader is None:
        raise SourceError(f"{case.id}: cannot import {path}")
    mod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mod)
    gen = getattr(mod, func, None)
    if not callable(gen):
        raise SourceError(f"{case.id}: {path} has no generator function {func!r}")
    return gen


def generate(case: TestCase, ctx: RunContext) -> list[tuple[Vec, DutSpec]]:
    """Every configuration of vector test ``case``: its stimulus and wrapper spec."""
    from xut.catalog import model as catalog_model

    src = case.source
    if not src:
        raise SourceError(f"{case.id}: test.yaml has no source")
    if src.endswith(".xvec"):
        path = case.test_dir / src
        vec = xvec.load(path)
        spec = spec_from_catalog(
            catalog_model.load_entry(case.family, case.prim, ctx.root),
            vec.cfg,
            vec.attrs,
            allow_illegal=vec.expect == "reject",
        )
        return [(vec, spec)]
    with _on_path(case.shared_dirs):
        gen = _import_generator(case, src)
        gctx = GenContext(case.family, case.prim, seed_for(case, ctx), root=ctx.root)
        vecs = list(gen(gctx))
    out = []
    for v in vecs:
        if not isinstance(v, Vec):
            raise SourceError(f"{case.id}: generator yielded {type(v).__name__}, not a Vec")
        if v.cfg not in gctx.specs:
            raise SourceError(f"{case.id}: configuration {v.cfg!r} was not built with ctx.dut(...)")
        out.append((v, gctx.specs[v.cfg]))
    return out


def _polarity_context(case: TestCase, ctx: RunContext) -> tuple[dict[str, str], dict]:
    """The catalog's declared port ``active`` levels and attribute defaults, for naming
    async/gate bins ``assert``/``release`` (``xut.golden.polarity_bins``). Without a
    declared level the bins stay ``rise``/``fall``."""
    from xut.catalog import model as catalog_model

    entry = catalog_model.load_entry(case.family, case.prim, ctx.root)
    active = {p["name"]: p["active"] for p in entry.ports if p.get("active")}
    return active, {a["name"]: a["default"] for a in entry.attributes}


class PythonRunner(Runner):
    name: ClassVar[str] = "python"
    x_observable: ClassVar[bool] = True
    styles: ClassVar[frozenset[str]] = frozenset({"vector"})

    def __init__(self) -> None:
        self._gen: dict[str, tuple[Vec, DutSpec]] = {}
        self._bins: set[str] = set()
        #: port -> declared active level, and attribute defaults (catalog; polarity_bins)
        self._active: dict[str, str] = {}
        self._defaults: dict[str, object] = {}
        self._seed: int | None = None
        self._deadline = float("inf")
        self._limit_s = 0

    def tools(self, ctx: RunContext) -> dict:
        return {"python": platform.python_version()}

    def configs(self, case: TestCase, ctx: RunContext) -> list[str]:
        """Run the generator; write ``configs.json`` before any configuration runs, so a
        configuration that later errors is still listed (review #10)."""
        self._limit_s = timeout_for(case, ctx)
        self._deadline = time.monotonic() + self._limit_s
        gen = _watchdog(lambda: generate(case, ctx), self._deadline, "generator", self._limit_s)
        names = [v.cfg for v, _ in gen]
        seeds = sorted({v.seed for v, _ in gen})
        if len(seeds) > 1:
            raise SourceError(f"{case.id}: configurations use different seeds {seeds}")
        self._seed = seeds[0] if seeds else None
        bad = [n for n in names if not is_cfg(n)]
        dups = sorted({n for n in names if names.count(n) > 1})
        if bad or dups:
            raise SourceError(f"{case.id}: bad configuration names {bad} / duplicates {dups}")
        self._gen = {v.cfg: (v, s) for v, s in gen}
        self._bins = set()
        self._active, self._defaults = _polarity_context(case, ctx)
        d = workdir(ctx, self.name, case.id)
        (d / "configs.json").write_text(json.dumps(names, indent=1) + "\n")
        return names

    def run_config(self, case: TestCase, cfg: str, cfgdir: Path, ctx: RunContext) -> ConfigResult:
        vec, spec = self._gen[cfg]
        log: list[str] = [f"python golden run of {case.id} cfg {cfg}\n"]
        try:
            m = write_dut(spec, cfgdir / "dut")
            report = validate(vec, m)
            if report.errors:
                return ConfigResult(
                    cfg,
                    "error",
                    "stimulus violates class rules (a generator bug): "
                    + "; ".join(report.errors[:3]),
                )
            mark(vec, report)
            xvec.dump(vec, cfgdir / "stim.xvec")
            stim_sha = sha256_file(cfgdir / "stim.xvec")
            log.append(f"stim.xvec: hw_renderable={vec.hw_renderable} {vec.hw_reason}\n")
            bins: set[str] = set()  # a reject configuration reaches nothing
            if vec.expect == "reject":
                # No behaviour to model: a header-only expectation, so the other runners
                # find the configuration and apply the reject rule (Task 9).
                trace = xtr.Trace(
                    {
                        "runner": self.name,
                        "flow": ctx.flow,
                        "model": "golden",
                        "seed": str(vec.seed),
                        "kind": "expected",
                        "prim": vec.prim,
                        "cfg": vec.cfg,
                        "expect": "reject",
                    }
                )
            else:
                try:
                    model_cls = registry.get(case.family, case.prim)
                except LookupError as e:
                    return ConfigResult(cfg, "skip", f"no golden model: {e}", stim_sha)
                try:
                    trace, reach = _watchdog(
                        lambda: replay(model_cls, vec, m),
                        self._deadline,
                        f"golden model ({cfg})",
                        self._limit_s,
                    )
                except ModelUnsupported as e:
                    return ConfigResult(cfg, "skip", f"model unsupported: {e}", stim_sha)
                except InvalidStimulus as e:
                    return ConfigResult(cfg, "error", str(e), stim_sha)
                except ModelContractError as e:
                    return ConfigResult(cfg, "error", f"golden model bug: {e}", stim_sha)
                if not trace.samples:  # validate refuses this; zero evidence never passes
                    return ConfigResult(cfg, "error", "golden replay has no samples", stim_sha)
                trace.header["flow"] = ctx.flow
                bins = reach.bins()
                if self._active:
                    bins = polarity_bins(bins, self._active, {**self._defaults, **vec.attrs})
                self._bins |= bins
            xtr.dump(trace, cfgdir / "expected.xtr")
            shutil.copyfile(cfgdir / "expected.xtr", cfgdir / "trace.xtr")
            log.append(f"expected.xtr: {len(trace.samples)} sample(s)\n")
            return ConfigResult(
                cfg,
                "pass",
                None,
                stim_sha,
                sha256_file(cfgdir / "expected.xtr"),
                0,
                sorted(bins),
            )
        finally:
            with (cfgdir / "run.log").open("a") as f:
                f.write("".join(log))

    def stimulus_seed(self, case: TestCase, ctx: RunContext) -> int | None:
        """The seed the stimuli were generated with (a frozen .xvec keeps its own)."""
        return self._seed

    def finish(self, case: TestCase, ctx: RunContext, d: Path, res: RunResult) -> None:
        res.bins_reached = sorted(self._bins)
