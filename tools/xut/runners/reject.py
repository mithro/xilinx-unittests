# SPDX-License-Identifier: Apache-2.0
"""The one ``expect=reject`` rule, shared by every simulator runner (rulings S13, S13a,
S13b).

A reject configuration drives an illegal attribute value; the simulator must refuse it.
The configuration declares WHICH attribute(s) are illegal (the stimulus header's
``illegal=``, from ``GenContext.dut(..., illegal=[...])``); ``xut.validate`` refuses a
reject stimulus that does not. A refusal counts as ``pass`` only on POSITIVE evidence,
never merely because the build or the run failed (a missing model, a broken include
path or a docker error must not look like a rejection):

- no illegal attribute declared -> ``error`` ("reject config must name its illegal
  attribute");
- acceptance: the run reached ``XUT_DONE`` -> ``fail`` ("expected rejection, got
  acceptance");
- any ``XUT_ERROR`` in the run (the testbench itself gave up) -> ``error``;
- any infrastructure diagnostic (``INFRA``: unknown module, missing include/file,
  docker, permissions, a failed xsim link) -> ``error``;
- compile/elaboration rejection: the build failed and an evidence line exists ->
  ``pass``;
- runtime rejection: the simulator exited cleanly (rc 0, e.g. via ``$finish``) without
  ``XUT_DONE`` and an evidence line exists -> ``pass``;
- anything else -> ``error``, with the diagnostic lines in the reason.

An *evidence* line has error or fatal severity -- the first severity word on it is
``error``, ``fatal`` or ``sorry`` (``Error:``, ``ERROR:``, ``Fatal:``, ``%Error``,
``Attribute Syntax Error``, ``file:3: error: ...``); a WARNING/NOTE/INFO line is never
evidence (a warning is the model *accepting* the value) -- and names one of the
declared illegal attributes, case-insensitively as a whole word. Both are matched only
outside file paths (quoted strings holding a "/" and any token containing "/"), ruling
S13a: a path such as ``.../<family>.FDRE.L0.illegal_init/...`` is never evidence.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from xut.formats import xtr
from xut.runners.base import ConfigResult, sha256_file

INFRA = re.compile(
    r"Unknown module type|Include file .* not found|Unable to open|No such file|docker:"
    r"|permission denied|cannot find"
    # xsim: an unresolved module (VRFC 10-2063), a missing file, a failed link
    r"|Module <[^>]*> not found|cannot open (include )?file|Failed to link the design",
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


#: An informational line: never a diagnostic, never evidence (ruling S13a).
_INFO = re.compile(r"^\s*(INFO|NOTE)\b", re.IGNORECASE)
#: A double-quoted string holding a path, then any other token containing "/".
_QUOTED_PATH = re.compile(r'"[^"]*/[^"]*"')
_PATH_TOKEN = re.compile(r"\S*/\S*")


def _scrubbed(line: str) -> str:
    """``line`` without file paths (quoted or bare: anything containing "/"), or ""
    for an INFO/NOTE line. Evidence is matched on this only (ruling S13a): a test
    directory such as ``<family>.FDRE.L0.illegal_init/`` must never count as a
    diagnostic naming the attribute."""
    if _INFO.match(line):
        return ""
    return _PATH_TOKEN.sub(" ", _QUOTED_PATH.sub(" ", line))


def _lines(text: str, pattern: re.Pattern[str]) -> list[str]:
    """The lines of ``text`` whose scrubbed form matches ``pattern``."""
    return [ln.strip() for ln in text.splitlines() if pattern.search(_scrubbed(ln))]


#: The first severity word of a line decides its severity.
_SEVERITY = re.compile(r"\b(error|fatal|sorry|warning|note|info)\b", re.IGNORECASE)


def is_error_line(line: str) -> bool:
    """``line`` has error/fatal severity: outside file paths and INFO/NOTE lines, its
    FIRST severity word is error, fatal or sorry (so ``file:3: warning: ... invalid``
    and ``WARNING: ... error`` are not). Shared with ``xut.runners.sim.model_errors``."""
    m = _SEVERITY.search(_scrubbed(line))
    return m is not None and m.group(1).lower() in ("error", "fatal", "sorry")


def _evidence(text: str, named: re.Pattern[str]) -> list[str]:
    """Error/fatal lines that name an illegal attribute, outside paths and INFO lines."""
    return [
        ln.strip() for ln in text.splitlines() if is_error_line(ln) and named.search(_scrubbed(ln))
    ]


def _show(lines: list[str]) -> str:
    shown = [ln[:_MAX_LINE] for ln in lines[:_MAX_LINES]]
    more = f" | ... ({len(lines) - _MAX_LINES} more)" if len(lines) > _MAX_LINES else ""
    return " | ".join(shown) + more if shown else "(no diagnostic)"


def reject_result(cfg: str, out: SimOutcome, illegal: Sequence[str]) -> ConfigResult:
    """The ``expect=reject`` verdict for one configuration (see the module docstring);
    ``illegal`` are the attribute names the configuration declares illegal."""
    names = sorted(set(illegal))
    if not names:
        return ConfigResult(
            cfg,
            "error",
            "reject config must name its illegal attribute (stimulus header illegal=; "
            "GenContext.dut(..., illegal=[...]))",
        )
    named = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    what = "/".join(names)
    both = out.compile_text + "\n" + out.run_text
    if out.run_rc is not None and "XUT_DONE" in out.run_text:
        return ConfigResult(
            cfg, "fail", f"expected rejection, got acceptance: the run reached XUT_DONE ({what})"
        )
    tb_errors = [ln.strip() for ln in out.run_text.splitlines() if "XUT_ERROR" in ln]
    if tb_errors:
        return ConfigResult(cfg, "error", f"testbench error, not a rejection: {_show(tb_errors)}")
    # INFRA is matched on whole lines, paths included: erring towards error is safe.
    infra = [ln.strip() for ln in both.splitlines() if INFRA.search(ln)]
    if infra:
        return ConfigResult(
            cfg, "error", f"infrastructure failure, not a rejection: {_show(infra)}"
        )
    if not out.compiled_ok:
        ev = _evidence(out.compile_text, named)
        if ev:
            return ConfigResult(
                cfg, "pass", f"rejected at compile/elaboration: {ev[0][:_MAX_LINE]}"
            )
        return ConfigResult(
            cfg,
            "error",
            f"compile failed without an error/fatal diagnostic naming {what}: "
            f"{_show(_lines(out.compile_text, DIAGNOSTIC))}",
        )
    if out.run_rc != 0:
        return ConfigResult(
            cfg,
            "error",
            f"simulator exited with rc {out.run_rc} (not a clean rejection): "
            f"{_show(_lines(out.run_text, DIAGNOSTIC))}",
        )
    ev = _evidence(out.run_text, named)
    if ev:
        return ConfigResult(cfg, "pass", f"rejected at runtime: {ev[0][:_MAX_LINE]}")
    return ConfigResult(
        cfg,
        "error",
        f"run ended without XUT_DONE and without an error/fatal diagnostic naming {what}: "
        f"{_show(_lines(out.run_text, DIAGNOSTIC))}",
    )


def reject_check(
    cd: Path, out: SimOutcome, illegal: Sequence[str], header: dict[str, str]
) -> ConfigResult:
    """``reject_result`` for configuration directory ``cd`` plus its evidence: a
    header-only ``trace.xtr`` (``expect=reject``, like the python run's expected trace)
    and the stimulus and trace hashes (a pass must leave a trace, Task 8). The
    configuration is ``header["cfg"]``."""
    r = reject_result(header["cfg"], out, illegal)
    xtr.dump(xtr.Trace({**header, "expect": "reject"}), cd / "trace.xtr")
    r.stimulus_sha256 = sha256_file(cd / "stim.xvec")
    r.trace_sha256 = sha256_file(cd / "trace.xtr")
    return r
