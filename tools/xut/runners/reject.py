# SPDX-License-Identifier: Apache-2.0
"""The one ``expect=reject`` rule, shared by every simulator runner (ruling S13).

A reject configuration drives an illegal attribute value; the simulator must refuse it.
A refusal counts as ``pass`` only on POSITIVE evidence, never merely because the build
or the run failed (a missing model, a broken include path or a docker error must not
look like a rejection):

- acceptance: the run reached ``XUT_DONE`` -> ``fail`` ("expected rejection, got
  acceptance");
- any infrastructure diagnostic (``INFRA``: unknown module, missing include/file,
  docker, permissions) -> ``error``;
- compile/elaboration rejection: the build failed and a diagnostic line names a
  rejected attribute -> ``pass``;
- runtime rejection: the simulator exited cleanly (rc 0, e.g. via ``$finish``) without
  ``XUT_DONE`` and a diagnostic line names a rejected attribute -> ``pass``;
- anything else -> ``error``, with the diagnostic lines in the reason.

The names searched for are the configuration's attribute names (``attr.<NAME>`` of the
stimulus), case-insensitively as whole words; only a configuration without attributes
falls back to the primitive's name. A *diagnostic* line is one that says error,
illegal, invalid, not allowed, out of range or violation (UNISIM's "Attribute Syntax
Error", "DRC Error", ...).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from xut.formats import xtr
from xut.runners.base import ConfigResult, sha256_file

INFRA = re.compile(
    r"Unknown module type|Include file .* not found|Unable to open|No such file|docker:"
    r"|permission denied|cannot find",
    re.IGNORECASE,
)
DIAGNOSTIC = re.compile(
    r"error|illegal|invalid|not allowed|out of range|violat|sorry", re.IGNORECASE
)
_MAX_LINES = 3
_MAX_LINE = 200


@dataclass(frozen=True)
class SimOutcome:
    """What one build + run produced. Texts exclude the executor's ``$ argv`` lines."""

    compiled_ok: bool
    compile_text: str
    run_rc: int | None  # None: not run (the build failed)
    run_text: str


def _lines(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if pattern.search(ln)]


def _show(lines: list[str]) -> str:
    shown = [ln[:_MAX_LINE] for ln in lines[:_MAX_LINES]]
    more = f" | ... ({len(lines) - _MAX_LINES} more)" if len(lines) > _MAX_LINES else ""
    return " | ".join(shown) + more if shown else "(no diagnostic)"


def reject_result(cfg: str, out: SimOutcome, attrs: Iterable[str], prim: str) -> ConfigResult:
    """The ``expect=reject`` verdict for one configuration (see the module docstring)."""
    names = sorted(set(attrs)) or [prim]
    named = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    what = "/".join(names)
    both = out.compile_text + "\n" + out.run_text
    if out.run_rc is not None and "XUT_DONE" in out.run_text:
        return ConfigResult(
            cfg, "fail", f"expected rejection, got acceptance: the run reached XUT_DONE ({what})"
        )
    infra = _lines(both, INFRA)
    if infra:
        return ConfigResult(
            cfg, "error", f"infrastructure failure, not a rejection: {_show(infra)}"
        )
    if not out.compiled_ok:
        ev = [ln for ln in _lines(out.compile_text, DIAGNOSTIC) if named.search(ln)]
        if ev:
            return ConfigResult(
                cfg, "pass", f"rejected at compile/elaboration: {ev[0][:_MAX_LINE]}"
            )
        return ConfigResult(
            cfg,
            "error",
            f"compile failed without a diagnostic naming {what}: "
            f"{_show(_lines(out.compile_text, DIAGNOSTIC))}",
        )
    if out.run_rc != 0:
        return ConfigResult(
            cfg,
            "error",
            f"simulator exited with rc {out.run_rc} (not a clean rejection): "
            f"{_show(_lines(out.run_text, DIAGNOSTIC))}",
        )
    ev = [ln for ln in _lines(out.run_text, DIAGNOSTIC) if named.search(ln)]
    if ev:
        return ConfigResult(cfg, "pass", f"rejected at runtime: {ev[0][:_MAX_LINE]}")
    return ConfigResult(
        cfg,
        "error",
        f"run ended without XUT_DONE and without a diagnostic naming {what}: "
        f"{_show(_lines(out.run_text, DIAGNOSTIC))}",
    )


def reject_check(
    cd: Path, out: SimOutcome, attrs: Iterable[str], prim: str, header: dict[str, str]
) -> ConfigResult:
    """``reject_result`` for configuration directory ``cd`` plus its evidence: a
    header-only ``trace.xtr`` (``expect=reject``, like the python run's expected trace)
    and the stimulus and trace hashes (a pass must leave a trace, Task 8)."""
    r = reject_result(cd.name[4:], out, attrs, prim)
    xtr.dump(xtr.Trace({**header, "expect": "reject"}), cd / "trace.xtr")
    r.stimulus_sha256 = sha256_file(cd / "stim.xvec")
    r.trace_sha256 = sha256_file(cd / "trace.xtr")
    return r
