# SPDX-License-Identifier: Apache-2.0
"""The portability smoke run and ``status/PORTABILITY.md`` (spec §6.2 "Portability table").

``run_smoke`` compiles and briefly runs every UNISIM model of a model source on Icarus and
on Verilator (after ``xut verilatorize``), in the simulator container:

* **Models**: every ``unisims/*.v``, plus the ``retarget/*.v`` files of the catalog
  entries whose ``model.library`` is ``retarget``.
* **Configurations** (review #3): the default parameters, every ``generate_configs`` entry
  (Task 12: the overrides that elaborate every generate branch), and each
  ``IS_*_INVERTED`` parameter flipped on its own. A model is ``yes`` on a simulator only if
  every configuration compiles and runs to ``XUT_SMOKE_OK``; otherwise the reason names the
  first configuration that does not, its category (``classify``) and its first error line.
  When every failing configuration is ``config`` (the model's own attribute check refused
  it, ruling S51) the cell is ``no: config: <why> [<key>]``: ``xut lint`` then warns, as the
  run says nothing about the simulator. (Legal smoke configurations from the units'
  overrides are a follow-up.)
* **Smoke top** (``smoke_top``): every input tied low, every output and inout left as a
  wire, the overrides passed as ``#(.NAME(value))``, and a ``#200000`` run so a runtime
  ``$finish`` (a model's own attribute check) is caught.
* **Verilator** builds with the runner's flags (``xut.runners.verilator.verilator_argv``)
  and resolves models from the verilatorized directory first, so a transformed model (and
  a transformed dependency) is used exactly as the ``verilator`` runner uses it. A model
  the transform refused is ``no: verilatorize: <reason>``, and a model whose hierarchy holds
  one is ``no: blocked by refused dependency <X>`` (ruling S45/S47), neither built.
* **Equivalence** (``equiv``): ``run_smoke`` runs ``xut verilatorize --check`` over the models
  first, so every gated model (transformed, or over a transformed dependency: ruling S45)
  has its verdicts; the column is ``pass`` (all configurations), ``fail``, ``error``,
  ``blocked`` (a refused dependency: never checked, its Verilator results are refused
  anyway) or ``—`` (not gated, or no verdict: ``xut lint`` refuses the latter).

The work goes in ``build/portability/<model-source>/<MODEL>/<config_dir>/`` (``smoke.v``,
``iverilog.sh``, ``verilator.sh``); each script writes ``<tool>.log`` and ``<tool>.rc`` and
appends its name to ``done.txt``. ``_run_scripts`` runs every script in its own
memory-capped container (Ruling S48: ``xut.container.DockerExecutor``), ``jobs`` at a time,
in ``jobs.txt`` order (the slowest first), each container's own log in
``<tool>.container.log``, while ``run_smoke`` prints ``progress: done=N total=M
elapsed_s=E`` every 10 s. A container the kernel OOM-killed at its cap is category ``oom``:
the host copies the executor's ``xut-container: oom-killed`` line into ``<tool>.log`` and,
if the script was killed before it could, writes ``<tool>.rc`` (137) and its ``done.txt``
line itself. An infrastructure failure (a host exception such as ``ContainerError``, or
docker run's own exit 125) is category ``infra-error`` (``INFRA_MARK``): the model never
ran, so ``xut lint`` asks for the table to be regenerated rather than for tests to declare
the simulator unsupported.
The rows go to ``build/portability/<model-source>.json`` (a ``--models`` run: under
``build/portability/partial/``, never mistaken for a full table, and its work directory is
``build/portability/partial/<model-source>/``, so it never deletes a full run's).

``render`` writes the table and ``parse`` reads it back (``xut lint``: rules
``portability-agreement`` and ``verilatorize-equiv``).
"""

from __future__ import annotations

import fnmatch
import json
import multiprocessing
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from xut import provenance
from xut.catalog.unisim import HdlModule, HdlParam, parse_module
from xut.errors import XutError
from xut.modelsrc import ModelSource

if TYPE_CHECKING:
    from xut.container import Executor
    from xut.verilatorize.driver import ModelEntry

CATEGORIES = (
    "infra-error", "config", "udp", "tri0-tri1", "real", "secureip", "strength", "deassign",
    "oom", "timeout", "other",
)  # fmt: skip
SMOKE_OK = "XUT_SMOKE_OK"
#: 124 (``timeout``'s own exit) is a timeout; 137 (SIGKILL) is ``timeout -k``'s kill or an
#: OOM kill, which docker's ``State.OOMKilled`` tells apart (``xut-container: oom-killed``:
#: checked on this host for a child killed at the cap while the main process exits 0);
#: without that mark a 137 is reported as a timeout, its log line saying ``timeout-or-kill``
TIMEOUT_MARK = "xut-smoke: timeout"
#: the host's note for an infrastructure failure (a host exception, docker run's own exit
#: 125): the model never ran, so the cell is category ``infra-error``, never a model verdict
INFRA_MARK = "xut-smoke: infra-error:"
#: docker run's own failure (the container never started)
DOCKER_RUN_FAILED = 125
#: the host's note when a script wrote no rc: the container's exit code and last log line
CONTAINER_EXIT = "xut-container: exit"
TOOLS = ("iverilog", "verilator")
NONE = "—"
EQUIV = ("pass", "fail", "error", "blocked", NONE)
#: per-script limits (``timeout`` in the container); the whole run's limit
BUILD_TIMEOUT_S = 1800
RUN_TIMEOUT_S = 600
#: one script's container: its build and run limits plus the ``timeout -k`` grace
JOB_TIMEOUT_S = BUILD_TIMEOUT_S + RUN_TIMEOUT_S + 120
POLL_S = 10
_MAX = 200
_GENERATED = "<!-- GENERATED by xut portability — do not edit -->"
_INVERTED = re.compile(r"IS_\w+_INVERTED")
_LITERAL = re.compile(r"(\d+)'([bBhHdDoO])([0-9a-fA-F_]+)")


class PortabilityError(XutError):
    """A malformed portability table or result file."""


@dataclass
class Row:
    """One model's row. ``iverilog``/``verilator`` are ``yes``, ``no`` (the reason is in
    ``reason``), ``no: <why>`` (not built: ruling S47) or ``no: config: <why> [<key>]`` (the
    smoke configuration is illegal for the model: ruling S51); ``verilatorize`` is the
    manifest status, with ``(gated: <deps>)`` when its hierarchy holds transformed
    models."""

    model: str
    iverilog: str
    verilator: str
    verilatorize: str
    equiv: str
    triggers: list[str] = field(default_factory=list)
    enablers: list[str] = field(default_factory=list)
    reason: str = ""

    def config(self, tool: str) -> bool:
        """``tool``'s cell is ``no: config: ...``: every failing smoke configuration was
        illegal for the model (ruling S51), which says nothing about the simulator."""
        return getattr(self, tool).startswith("no: config: ")

    @property
    def gated(self) -> bool:
        """Verilator results need an equivalence verdict (ruling S45)."""
        return self.verilatorize.split(" ")[0] == "transformed" or "(gated:" in self.verilatorize

    def ok(self, tool: str) -> bool:
        return getattr(self, tool) == "yes"

    def why(self, tool: str) -> str:
        """Why the model does not run on ``tool``: the cell's own reason, else the part of
        ``reason`` about ``tool``, else the whole reason."""
        cell = getattr(self, tool)
        if cell.startswith("no: "):
            return cell.removeprefix("no: ")
        parts = [p for p in self.reason.split("; ") if p.startswith(f"{tool}: ")]
        return "; ".join(p.removeprefix(f"{tool}: ") for p in parts) or self.reason or "no reason"


# ---- the smoke top ------------------------------------------------------------------------
def _range(width: int) -> str:
    return f"[{width - 1}:0] "


def smoke_top(mod: HdlModule, attrs: dict[str, str] | None = None) -> str:
    """The smoke testbench ``xut_smoke`` for ``mod`` (module docstring), with ``attrs``
    (Verilog literals) as parameter overrides."""
    lines = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// GENERATED by xut portability",
        "`timescale 1ps / 1ps",
        "module xut_smoke;",
    ]
    conns = []
    for p in mod.ports:
        if p.direction == "input":
            lines.append(f"  reg  {_range(p.width)}i_{p.name} = 0;")
            conns.append(f".{p.name}(i_{p.name})")
        elif p.direction == "output":
            lines.append(f"  wire {_range(p.width)}o_{p.name};")
            conns.append(f".{p.name}(o_{p.name})")
        else:
            lines.append(f"  wire {_range(p.width)}io_{p.name};")
            conns.append(f".{p.name}(io_{p.name})")
    params = ""
    if attrs:
        params = " #(" + ", ".join(f".{k}({v})" for k, v in sorted(attrs.items())) + ")"
    body = ", ".join(conns)
    lines += [
        f"  {mod.name}{params} dut ({body});",
        f'  initial begin #200000; $display("{SMOKE_OK}"); $finish; end',
        "endmodule",
    ]
    return "\n".join(lines) + "\n"


# ---- classification -------------------------------------------------------------------------
_ERROR_LINE = re.compile(r"%Error|\berror\b|\bsorry\b|unsupported|unknown module", re.I)
_CATEGORY_RULES = (
    ("secureip", re.compile(r"\bSIP_\w+|secureip|encrypt|pragma protect", re.I)),
    ("udp", re.compile(r"\budps?\b|user.defined primitive", re.I)),
    ("tri0-tri1", re.compile(r"\btri[01]\b", re.I)),
    ("deassign", re.compile(r"deassign|procedural (continuous )?assign", re.I)),
    ("strength", re.compile(r"strength", re.I)),
    ("real", re.compile(r"\breal\b|\bshortreal\b|\brealtime\b", re.I)),
)


#: A UNISIM model's own attribute/legality check stopping the smoke run (ruling S51): the
#: smoke configuration is illegal for the model, which says nothing about the simulator.
#: Taken from the 2025.2 smoke logs (DSP48E1, MMCME2_ADV, PLLE2_ADV, RAMB18E1, ...).
_CONFIG_RULES = (
    # "Attribute Syntax Error : The attribute ACASCREG  on DSP48E1 instance ... is set to 1.
    #  ACASCREG has to be set to 0 when attribute AREG = 0." (also RAMB18E1/36E1 READ_WIDTH,
    #  PLLE2_ADV CLKIN1_PERIOD)
    re.compile(r"^\s*Attribute Syntax Error\b"),
    # "Error: [Unisim MMCME2_ADV-6] The attribute CLKIN2_PERIOD is set to 0.000000 ns and
    #  out of the allowed range 0.938000 ns to 100.000000 ns" (also PLLE3/4_ADV)
    re.compile(r"\[Unisim \w+-\d+\] The attribute \w+ is set to .*\ballowed (?:range|values?)\b"),
    # "Error: [Unisim ...-n] DEVICE_ID attribute is not set."
    re.compile(r"\[Unisim \w+-\d+\] \w+ attribute is not set\b"),
    # "Error: [Unisim SYSMONE1-4] The analog data file design.txt was not found. Use the
    #  SIM_MONITOR_FILE parameter to specify the analog data file name ..."
    re.compile(r"\[Unisim \w+-\d+\] The analog data file .* Use the SIM_MONITOR_FILE parameter"),
)
#: A module the model instantiates that the simulator cannot find (Icarus; Verilator)
_MISSING_MODULE = (
    re.compile(r"Unknown module type: (\w+)"),
    re.compile(r"Cannot find file containing module: '(\w+)'"),
)


def missing_modules(log_text: str) -> list[str]:
    """The modules a smoke log's error lines say are missing."""
    lines = error_lines(log_text)
    return [m.group(1) for ln in lines for rx in _MISSING_MODULE if (m := rx.search(ln))]


def error_lines(log_text: str) -> list[str]:
    """The lines of a log that report an error (Verilator warnings excluded)."""
    return [
        ln.strip()
        for ln in log_text.splitlines()
        if _ERROR_LINE.search(ln)
        and not ln.lstrip().startswith(("%Warning", "$ "))
        and (not ln.startswith("xut-smoke:") or ln.startswith(INFRA_MARK))
    ]


_EXIT_LINE = re.compile(r"^xut-smoke: (?:build|run) exit (\d+)\s*$", re.M)


def _is_config(line: str) -> bool:
    return any(rx.search(line) for rx in _CONFIG_RULES)


def _crashed(log_text: str, rc: int | None) -> bool:
    """A signal exit (>= 128) of the script or a step it logged, other than the
    timeout-or-kill path (``TIMEOUT_MARK``, classified before)."""
    codes = [int(c) for c in _EXIT_LINE.findall(log_text)] + ([rc] if rc is not None else [])
    return any(c >= 128 for c in codes)


def classify(log_text: str, known: AbstractSet[str] | None = None, rc: int | None = None) -> str:
    """The category of a failed smoke log (``CATEGORIES``): an infrastructure failure
    first (``INFRA_MARK``), then an OOM kill at the container's memory cap, then a timeout
    (an OOM-killed tool exits 137, which the script marks as ``timeout-or-kill``), then
    ``config`` when *every* error line is the model's own attribute/legality check
    (``_CONFIG_RULES``, rulings S51, S50a) and nothing crashed (``rc``, or a logged exit,
    >= 128), then ``secureip`` when every module the log says is missing is absent from
    the model source (``known``: its models; ruling S51), then the first category any
    non-config error line matches, else ``other``."""
    from xut.container import OOM_MARK

    if INFRA_MARK in log_text:
        return "infra-error"
    if OOM_MARK in log_text:
        return "oom"
    if TIMEOUT_MARK in log_text:
        return "timeout"
    lines = error_lines(log_text)
    if lines and all(_is_config(ln) for ln in lines) and not _crashed(log_text, rc):
        return "config"
    errors = [ln for ln in lines if not _is_config(ln)]
    missing = missing_modules(log_text)
    if known is not None and missing and not set(missing) & set(known):
        return "secureip"
    for name, rx in _CATEGORY_RULES:
        if any(rx.search(ln) for ln in errors):
            return name
    return "other"


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX else text[: _MAX - 1] + "…"


def failure(log_text: str, rc: int | None, known: AbstractSet[str] | None = None) -> str:
    """``<category>: <first error line>`` of a failed smoke log (an infrastructure failure:
    the host's note; an OOM kill: the line naming the memory cap; a script that wrote no
    rc: the host's container-exit note)."""
    from xut.container import OOM_MARK

    lines = log_text.splitlines()
    infra = [ln.removeprefix(INFRA_MARK).strip() for ln in lines if ln.startswith(INFRA_MARK)]
    oom = [ln.strip() for ln in lines if ln.startswith(OOM_MARK)]
    exits = [ln.strip() for ln in lines if ln.startswith(CONTAINER_EXIT)]
    category = classify(log_text, known, rc)
    errors = error_lines(log_text)
    if category != "config":  # the first error that is not a model's legality message
        errors = [ln for ln in errors if not _is_config(ln)] or errors
    first = (infra or oom or (exits if rc is None else []) or errors or [""])[0]
    if not first:
        first = f"exit {rc}, no {SMOKE_OK}" if rc is not None else "the script did not finish"
    return f"{category}: {_short(first)}"


# ---- configurations ------------------------------------------------------------------------
def flipped(p: HdlParam) -> str | None:
    """``p`` (an ``IS_*_INVERTED`` parameter) with every bit of its default inverted, as a
    Verilog literal; None when the default is not a plain literal."""
    if p.kind == "integer":
        return "0" if p.default else "1"
    if p.kind != "bits":
        return None
    m = _LITERAL.fullmatch(str(p.default).replace(" ", ""))
    if not m:
        return None
    width = p.width or int(m.group(1))
    base = {"b": 2, "h": 16, "d": 10, "o": 8}[m.group(2).lower()]
    value = int(m.group(3).replace("_", ""), base)
    return f"{width}'b{(~value) & ((1 << width) - 1):0{width}b}"


def configurations(path: Path, mod: HdlModule) -> tuple[list[dict[str, str]], list[str]]:
    """``[{}, *generate configurations, *one IS_*_INVERTED flipped each]`` (deduplicated)
    and notes (why no generate configuration could be derived)."""
    from xut.verilatorize.analyze import TransformError, generate_configs
    from xut.verilatorize.driver import model_choices

    notes: list[str] = []
    try:
        gen = generate_configs(path, mod.name, model_choices(path, mod.name))
    except TransformError as e:
        gen = []
        notes.append(f"no generate configurations: {_short(str(e))}")
    out: list[dict[str, str]] = [{}]
    flips = [(p.name, flipped(p)) for p in mod.params if _INVERTED.fullmatch(p.name)]
    for cfg in [*gen, *({name: v} for name, v in flips if v is not None)]:
        if cfg not in out:
            out.append(cfg)
    return out, notes


@dataclass
class _Plan:
    model: str
    path: Path
    mod: HdlModule | None
    configs: list[dict[str, str]]
    notes: list[str]
    error: str = ""


def _plan(model: str, path: Path) -> _Plan:
    """Runs in a worker process."""
    try:
        mod = parse_module(path, model)
    except (ValueError, OSError) as e:
        why = str(e).removeprefix(f"{path}: ")
        return _Plan(model, path, None, [], [], f"cannot read its ports: {_short(why)}")
    configs, notes = configurations(path, mod)
    return _Plan(model, path, mod, configs, notes)


def smoke_models(ms: ModelSource, root: Path) -> dict[str, Path]:
    """Every ``unisims/*.v`` of ``ms``, plus the ``retarget/*.v`` of the catalog entries of
    library ``retarget`` (a retarget file never shadows a UNISIM one)."""
    from xut.catalog.model import load_entry
    from xut.workunits import load_family

    out = {f.stem: f for f in sorted(ms.unisims.glob("*.v"))}
    if ms.retarget is not None:
        family = load_family(root)
        for f in sorted((root / "catalog" / family).glob("*.yaml")):
            if f.name.endswith(".overrides.yaml"):
                continue
            entry = load_entry(family, f.stem, root)
            model = Path(entry.model.get("file", f"{f.stem}.v")).stem
            if entry.model.get("library") == "retarget" and model not in out:
                rf = ms.retarget / f"{model}.v"
                if rf.is_file():
                    out[model] = rf
    return dict(sorted(out.items()))


# ---- the run ------------------------------------------------------------------------------
def out_dir(ms: ModelSource, root: Path, partial: bool = False) -> Path:
    """The work directory of a run: a partial (``--models``) run's lives under
    ``partial/``, so it never deletes a full run's (S48a M-4)."""
    base = root / "build" / "portability"
    return (base / "partial" if partial else base) / ms.name


def result_path(ms: ModelSource, root: Path, partial: bool = False) -> Path:
    base = root / "build" / "portability"
    return (base / "partial" if partial else base) / f"{ms.name}.json"


_SCRIPT = """\
#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# GENERATED by xut portability: {what}
cd "$(dirname "$0")" || exit 1
rc=0
timeout -k 10 {build_t} {build} > {tool}.log 2>&1 || rc=$?
echo "xut-smoke: build exit $rc" >> {tool}.log
if [ "$rc" -eq 0 ]; then
  timeout -k 10 {run_t} {run} >> {tool}.log 2>&1 || rc=$?
  echo "xut-smoke: run exit $rc" >> {tool}.log
fi
if [ "$rc" -eq 124 ]; then echo "{timeout_mark} ($rc)" >> {tool}.log; fi
if [ "$rc" -eq 137 ]; then echo "{timeout_mark}-or-kill ($rc)" >> {tool}.log; fi
{cleanup} >> {tool}.log 2>&1
echo "$rc" > {tool}.rc
echo "{name}" >> ../../done.txt
"""


def _scripts(ex: Executor, ms: ModelSource, root: Path, d: Path, key: str, model: str) -> dict:
    from xut.runners.base import RunContext
    from xut.runners.verilator import verilator_argv
    from xut.verilatorize.driver import vz_dir

    g = ex.guest
    glbl = g(ms.glbl)
    libs = [a for p in ms.search for a in ("-y", g(p))]
    ivl = ["iverilog", "-g2012", "-o", "sim.vvp", "-s", "xut_smoke", "-s", "glbl", *libs]
    ivl += ["-Y", ".v", "smoke.v", glbl]
    ctx = RunContext(root, "rtl", ms)
    vl = verilator_argv(ex, ctx, vz_dir(ms, root), ["smoke.v", glbl], [])
    rel = f"{d.parent.name}/{d.name}"
    common = {"build_t": BUILD_TIMEOUT_S, "run_t": RUN_TIMEOUT_S, "timeout_mark": TIMEOUT_MARK}
    return {
        "iverilog": _SCRIPT.format(
            what=f"{model} [{key}] on Icarus",
            tool="iverilog",
            build=shlex.join(ivl),
            run="vvp -n sim.vvp",
            cleanup="rm -fv sim.vvp",
            name=f"{rel}/iverilog",
            **common,
        ),
        "verilator": _SCRIPT.format(
            what=f"{model} [{key}] on Verilator",
            tool="verilator",
            build=shlex.join(vl),
            run="./obj/simx",
            cleanup="rm -rf obj && echo 'xut-smoke: obj/ removed'",
            name=f"{rel}/verilator",
            **common,
        ),
    }


def _gate(e: ModelEntry | None) -> str | None:
    """The Verilator cell of a model that is not built (ruling S47), or None."""
    if e is None:
        return "no: verilatorize: no manifest entry"
    if e.status == "unsupported":
        return f"no: verilatorize: {_short(e.reason.splitlines()[0] if e.reason else 'refused')}"
    if e.depends_on_unsupported:
        return f"no: blocked by refused dependency {', '.join(e.depends_on_unsupported)}"
    return None


def _vz_cell(e: ModelEntry | None) -> str:
    if e is None:
        return "unsupported"
    deps = e.depends_on_transformed
    return e.status + (f" (gated: {', '.join(deps)})" if deps else "")


def _equiv(
    e: ModelEntry | None, models: Mapping[str, ModelEntry], need: Iterable[str] = ("default",)
) -> tuple[str, str]:
    """The equiv cell of a manifest entry, and the reason part naming a non-pass. ``pass``
    needs a pass for every configuration of ``need`` (the default and the generate
    configurations, keyed canonically) and, for each, a pass of every transformed
    descendant for the parameterisation it instantiates (``models``: the manifest's
    entries; ruling S50): a descendant's ``fail``/``error`` is the cell, a missing verdict
    anywhere is ``—``."""
    from xut.verilatorize.driver import descendants_blocked

    if e is None or not e.gated:
        return NONE, ""
    if e.status == "unsupported" or e.depends_on_unsupported:
        return "blocked", ""
    verdicts = e.equiv
    for bad in ("fail", "error"):
        keys = sorted(k for k, v in verdicts.items() if v == bad)
        if keys:
            why = _short(e.equiv_reason.get(keys[0], "") or "see the manifest")
            return bad, f"equiv: {bad} [{keys[0]}] ({len(keys)} of {len(verdicts)}): {why}"
    if any(v != "pass" for v in verdicts.values()):
        return "error", "equiv: a verdict is neither pass, fail nor error"
    missing = sorted(set(need) - set(verdicts))
    if not verdicts or missing:
        return NONE, f"equiv: no verdict for [{(missing or ['default'])[0]}]"
    for key in sorted(verdicts):
        got = descendants_blocked(e, key, models.get)
        if got is not None:
            status, why = got
            cell = status if status in ("fail", "error") else NONE
            return cell, f"equiv: {cell} via {_short(why)} (under [{key}])"
    return "pass", ""


def _outcome(d: Path, tool: str, known: AbstractSet[str] | None = None) -> tuple[bool, str]:
    """Whether ``tool``'s smoke script in ``d`` passed, else ``failure``'s reason."""
    rc_file, log = d / f"{tool}.rc", d / f"{tool}.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    if not rc_file.is_file():
        return False, failure(text, None, known)
    raw = rc_file.read_text().strip()
    try:
        rc = int(raw)
    except ValueError:  # the script finished and wrote garbage: say so
        return False, f"{classify(text)}: unreadable {tool}.rc {_short(repr(raw))}"
    if rc == 0 and SMOKE_OK in text:
        return True, ""
    return False, failure(text, rc, known)


def tool_cell(
    dirs: list[tuple[str, Path]], tool: str, known: AbstractSet[str] | None = None
) -> tuple[str, str]:
    """``(cell, reason part)`` of ``tool`` over a model's configuration directories:
    ``yes``; ``no`` with the first failing configuration's reason; or, when every failing
    configuration is ``config`` (the model's own legality check refused the smoke
    configuration, ruling S51), ``no: config: <why> [<key>]``: a real failure in any
    configuration is never hidden behind an illegal one."""
    config = ""
    for key, d in dirs:
        ok, why = _outcome(d, tool, known)
        if ok:
            continue
        if why.startswith("config: "):
            config = config or f"no: {why} [{key}]"
            continue
        return "no", f"{tool}: {why} [{key}]"
    return (config, "") if config else ("yes", "")


def _done(done: Path) -> int:
    return len(done.read_text().splitlines()) if done.is_file() else 0


def _progress_loop(done: Path, total: int, stop: threading.Event, t0: float, out: Callable) -> None:
    while not stop.wait(POLL_S):
        out(f"progress: done={_done(done)} total={total} elapsed_s={time.monotonic() - t0:.0f}")


def _run_one(exe: Executor, work: Path, script: str, lock: threading.Lock) -> None:
    """Run ``script`` (``<MODEL>/<config_dir>/<tool>.sh``) in its own container, then
    record what the script could not: an OOM kill, a host-side timeout or error."""
    from xut.container import OOM_MARK, RunTimeout

    d, tool = work / Path(script).parent, Path(script).stem
    clog = d / f"{tool}.container.log"
    notes: list[str] = []
    timed_out, rc = False, None
    try:
        rc = exe.run(["bash", script], cwd=work, log=clog, timeout_s=JOB_TIMEOUT_S)
    except RunTimeout as e:
        timed_out = True
        notes.append(f"{TIMEOUT_MARK} (host: {e})")
    except (XutError, OSError, subprocess.SubprocessError) as e:
        notes.append(f"{INFRA_MARK} host error: {type(e).__name__}: {e}")
    text = clog.read_text(errors="replace") if clog.is_file() else ""
    oom = [ln.strip() for ln in text.splitlines() if ln.startswith(OOM_MARK)]
    notes = oom[:1] + notes
    has_rc = (d / f"{tool}.rc").is_file()
    if not has_rc and not oom and rc is not None:
        # the script never finished and nothing says why: docker run's own failure (S48a M-5)
        rest = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("$ ")]
        note = f"{CONTAINER_EXIT} {rc}: {rest[-1] if rest else '(no output)'}"
        # exit 125: docker run itself failed (the container never started): infrastructure
        notes.append(f"{INFRA_MARK} {note}" if rc == DOCKER_RUN_FAILED else note)
    if notes:
        with (d / f"{tool}.log").open("a") as f:
            f.write("".join(f"{n}\n" for n in notes))
    if not has_rc and (oom or timed_out):
        # killed before its last lines: the script wrote neither its rc nor done.txt
        (d / f"{tool}.rc").write_text("137\n" if oom else "124\n")
    # every script counts once, even one killed between its rc and done.txt (S48a M-7);
    # the script has exited, so its own done.txt line (if any) is already there
    name = str(Path(script).with_suffix(""))
    with lock:
        done = work / "done.txt"
        if name not in (done.read_text().splitlines() if done.is_file() else []):
            with done.open("a") as f:
                f.write(f"{name}\n")


def _run_scripts(
    exe: Executor, work: Path, scripts: list[str], jobs: int, progress: Callable[[str], None]
) -> None:
    """Every smoke script (paths relative to ``work``), each in its own container, ``jobs``
    at a time, started in ``scripts`` order; ``progress: done=`` lines every ``POLL_S``."""
    total, done = len(scripts), work / "done.txt"
    stop, t1, lock = threading.Event(), time.monotonic(), threading.Lock()
    progress(f"progress: done=0 total={total} elapsed_s=0")
    poller = threading.Thread(
        target=_progress_loop, args=(done, total, stop, t1, progress), daemon=True
    )
    poller.start()
    halt = threading.Event()

    def job(script: str) -> None:
        if halt.is_set():  # interrupted: never start another container
            return
        _run_one(exe, work, script, lock)

    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    try:
        futures = [pool.submit(job, s) for s in scripts]
        for fut in futures:
            fut.result()
    except KeyboardInterrupt:
        # S48a M-1: cancel the queue, then kill the running containers, not wait for them
        halt.set()
        pool.shutdown(wait=False, cancel_futures=True)
        from xut import container

        container.kill_live()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        stop.set()
        poller.join()
    progress(f"progress: done={_done(done)} total={total} elapsed_s={time.monotonic() - t1:.0f}")


def run_smoke(
    ms: ModelSource,
    *,
    jobs: int,
    models: str | None = None,
    root: Path | None = None,
    check: bool = True,
    progress: Callable[[str], None] = print,
) -> list[Row]:
    """The smoke run of ``ms`` (module docstring): every model, or those matching the glob
    ``models``; writes ``build/portability/<ms>.json`` (a ``models`` run: under
    ``partial/``) and returns the rows. ``check``: equivalence-check the gated models first
    (``xut verilatorize --check``); without it the manifest's verdicts are used as they are."""
    from xut.container import SIM_IMAGE, executor_for, image_digest, sim_tool_versions
    from xut.paths import repo_root
    from xut.verilatorize.driver import model_files, verilatorize, vz_dir

    root = Path(root) if root is not None else repo_root()
    todo = smoke_models(ms, root)
    if models:
        todo = {m: f for m, f in todo.items() if fnmatch.fnmatchcase(m, models)}
        if not todo:
            raise XutError(f"--models {models!r} matches no model of {ms.name}")
    t0 = time.monotonic()

    def phase(name: str) -> Callable[[str], None]:
        # the verilatorize phase's own progress lines, relabelled so that the
        # ``progress: done=`` lines are the smoke run's alone
        return lambda line: progress(line.replace("progress: ", f"progress: phase={name} ", 1))

    progress(f"portability {ms.name}: verilatorize {len(todo)} models (check={check})")
    man = verilatorize(
        ms, sorted(todo), jobs=jobs, progress=phase("verilatorize"), check=check,
        out_dir=vz_dir(ms, root),
    )  # fmt: skip
    progress(f"portability {ms.name}: planning configurations")
    ctx = multiprocessing.get_context("forkserver")
    with ProcessPoolExecutor(max_workers=max(1, jobs), mp_context=ctx) as ex:
        plans = list(ex.map(_plan, list(todo), list(todo.values())))
    work = out_dir(ms, root, partial=bool(models))
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    exe = executor_for(ms, root)
    tools = sim_tool_versions(exe, work)
    dirs, jobs_list = _write_scripts(exe, ms, root, work, plans, man.models)
    n_cfg = sum(len(v) for v in dirs.values())
    progress(
        f"portability {ms.name}: {len(plans)} models, {n_cfg} configurations, "
        f"{len(jobs_list)} scripts, {jobs} containers at a time (logs: "
        f"{work}/<MODEL>/<config>/<tool>.log)"
    )
    _run_scripts(exe, work, [j for _, j in jobs_list], jobs, progress)
    need = {m: _needed(ms, m, e) for m, e in man.models.items() if e.gated and m in todo}
    known = set(model_files(ms))
    rows = [
        _row(p, dirs[p.model], man.models.get(p.model), man.models, need.get(p.model, ()), known)
        for p in plans
    ]
    doc = {
        "model_source": ms.name,
        "generated": provenance.utc_stamp(),
        "head": provenance.short_head(root),
        "image": SIM_IMAGE,
        "digest": image_digest(SIM_IMAGE) or "native",
        "tools": tools,
        "models_glob": models,
        "models": len(rows),
        "configurations": n_cfg,
        "elapsed_s": round(time.monotonic() - t0),
        "rows": [asdict(r) for r in rows],
    }
    dest = result_path(ms, root, partial=bool(models))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    progress(f"portability {ms.name}: wrote {dest}")
    return rows


def _write_scripts(
    exe: Executor,
    ms: ModelSource,
    root: Path,
    work: Path,
    plans: list[_Plan],
    entries: Mapping[str, ModelEntry],
) -> tuple[dict[str, list[tuple[str, Path]]], list[tuple[int, str]]]:
    """Each plan's configuration directories under ``work`` (``smoke.v`` and the scripts:
    no Verilator script for a model that is not built, ruling S47), ``jobs.txt`` (the
    slowest first: Verilator, then the largest models) and an empty ``done.txt``. Returns
    ``(model -> [(config key, dir)], [(weight, script)])``."""
    from xut.verilatorize.equiv import config_dir, config_key

    jobs_list: list[tuple[int, str]] = []
    dirs: dict[str, list[tuple[str, Path]]] = {}
    for p in plans:
        dirs[p.model] = []
        if p.mod is None:
            continue
        built = _gate(entries.get(p.model)) is None
        size = p.path.stat().st_size
        for cfg in p.configs:
            key = config_key(cfg)
            d = work / p.model / config_dir(key)
            d.mkdir(parents=True)
            (d / "smoke.v").write_text(smoke_top(p.mod, cfg))
            scripts = _scripts(exe, ms, root, d, key, p.model)
            for tool in TOOLS if built else ("iverilog",):
                (d / f"{tool}.sh").write_text(scripts[tool])
                weight = size * (4 if tool == "verilator" else 1)
                jobs_list.append((weight, f"{p.model}/{d.name}/{tool}.sh"))
            dirs[p.model].append((key, d))
    jobs_list.sort(key=lambda j: (-j[0], j[1]))
    (work / "jobs.txt").write_text("".join(f"{j}\n" for _, j in jobs_list))
    (work / "done.txt").write_text("")
    return dirs, jobs_list


def _needed(ms: ModelSource, model: str, e: ModelEntry) -> list[str]:
    """The configuration keys a gated model needs a verdict for: the default and its generate
    configurations, keyed as ``xut verilatorize --check`` keys them (``model_attrs``)."""
    from xut.verilatorize.driver import model_attrs
    from xut.verilatorize.equiv import config_key

    keys = {"default", *(config_key(model_attrs(ms, model, c)) for c in e.generate_configs)}
    return sorted(keys)


def _row(
    p: _Plan,
    dirs: list[tuple[str, Path]],
    e: ModelEntry | None,
    models: Mapping[str, ModelEntry] | None = None,
    need: Iterable[str] = ("default",),
    known: AbstractSet[str] | None = None,
) -> Row:
    equiv, equiv_why = _equiv(e, models or {}, need)
    vz = _vz_cell(e)
    trig = list(getattr(e, "triggers", []) or [])
    en = list(getattr(e, "enablers", []) or [])
    gate = _gate(e)
    if p.mod is None:  # no smoke top: neither simulator ran (a refused model stays refused)
        why = f"other: smoke: {p.error}"
        parts = [f"iverilog: {why}", *([] if gate else [f"verilator: {why}"]), equiv_why]
        return Row(p.model, "no", gate or "no", vz, equiv, trig, en, "; ".join(filter(None, parts)))
    cells, reasons = {}, []
    for tool in TOOLS:
        if tool == "verilator" and gate is not None:
            cells[tool] = gate
            continue
        cells[tool], why = tool_cell(dirs, tool, known)
        reasons += [why] if why else []
    reasons += [w for w in (equiv_why, *(f"note: {n}" for n in p.notes)) if w]
    return Row(
        p.model, cells["iverilog"], cells["verilator"], vz, equiv, trig, en, "; ".join(reasons)
    )


# ---- the table ----------------------------------------------------------------------------
_HEADER = "| Model | iverilog | verilator | verilatorize | equiv | triggers | enablers | reason |"


def _esc(text: str) -> str:
    return " ".join(text.split()).replace("\\", "\\\\").replace("|", "\\|")


def _unesc(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def _cells(line: str) -> list[str]:
    """The cells of a table line, split on unescaped ``|``."""
    body = line.strip()
    if not (body.startswith("|") and body.endswith("|")):
        raise PortabilityError(f"not a table line: {line!r}")
    parts = re.split(r"(?<!\\)\|", body[1:-1])  # an escaped backslash before | is kept as text
    return [_unesc(c.strip()) for c in parts]


def render(rows_by_source: dict[str, list[Row]], meta: dict) -> str:
    """``status/PORTABILITY.md``: one section per model source, a yes/no count per simulator,
    then one row per model. ``meta``: ``generated``, ``head``, ``image``, ``digest``, and
    optionally ``sources`` (model source -> its run's ``generated``/``head``/``models``/
    ``configurations``/``models_glob``)."""
    out = [
        _GENERATED,
        "# UNISIM portability",
        "",
        f"Generated by `xut portability` on {meta['generated']} at {meta['head']}. "
        f"Container {meta['image']} {meta['digest']}.",
    ]
    for ms, rows in rows_by_source.items():
        out += ["", f"## {ms}", ""]
        info = (meta.get("sources") or {}).get(ms)
        if info:
            glob = (
                f"; partial run, --models {info['models_glob']}" if info.get("models_glob") else ""
            )
            out += [
                f"_Smoke run {info['generated']} at {info['head']}: {info['models']} models, "
                f"{info['configurations']} configurations{glob}._",
                "",
            ]
        out += ["| simulator | yes | no | config |", "|---|---|---|---|"]
        for tool in TOOLS:
            yes = sum(r.ok(tool) for r in rows)
            config = sum(r.config(tool) for r in rows)
            out.append(f"| {tool} | {yes} | {len(rows) - yes - config} | {config} |")
        out += [
            "",
            "_config: every failing smoke configuration was refused by the model's own "
            "attribute check (ruling S51); the smoke run says nothing about the simulator._",
        ]
        out += ["", _HEADER, "|---|---|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: r.model):
            cells = [
                r.model, r.iverilog, r.verilator, r.verilatorize, r.equiv,
                ", ".join(r.triggers) or NONE, ", ".join(r.enablers) or NONE, r.reason,
            ]  # fmt: skip
            out.append("| " + " | ".join(_esc(c) for c in cells) + " |")
    return "\n".join(out) + "\n"


def parse(md: str) -> dict[str, dict[str, Row]]:
    """The inverse of ``render``: model source -> model -> ``Row``. Raises
    ``PortabilityError`` on a model row that is not well formed."""
    out: dict[str, dict[str, Row]] = {}
    section: dict[str, Row] | None = None
    in_rows = False
    for line in md.splitlines():
        if line.startswith("## "):
            section = out.setdefault(line[3:].strip(), {})
            in_rows = False
            continue
        if section is None or not line.startswith("|"):
            in_rows = in_rows and line.startswith("|")
            continue
        if line.strip() == _HEADER:
            in_rows = True
            continue
        if not in_rows or line.startswith("|---"):
            continue
        c = _cells(line)
        if len(c) != 8:
            raise PortabilityError(f"a model row needs 8 cells, got {len(c)}: {line!r}")
        if c[4] not in EQUIV:
            raise PortabilityError(f"{c[0]}: equiv cell {c[4]!r} is not one of {EQUIV}")
        for cell in (c[1], c[2]):
            if cell not in ("yes", "no") and not cell.startswith("no: "):
                raise PortabilityError(f"{c[0]}: simulator cell {cell!r} is not yes/no/no: ...")
        trig, en = ([] if v == NONE else v.split(", ") for v in (c[5], c[6]))
        section[c[0]] = Row(c[0], c[1], c[2], c[3], c[4], trig, en, c[7])
    return out


# ---- result files -------------------------------------------------------------------------
def load_results(root: Path) -> tuple[dict[str, list[Row]], dict]:
    """The full-run results in ``build/portability/*.json`` (partial runs excluded): rows by
    model source, and the ``render`` meta (the newest run's header, every run's info)."""
    rows: dict[str, list[Row]] = {}
    sources: dict[str, dict] = {}
    newest: dict = {}
    for f in sorted((Path(root) / "build" / "portability").glob("*.json")):
        try:
            doc = json.loads(f.read_text())
            if doc.get("models_glob"):
                continue
            rows[doc["model_source"]] = [Row(**r) for r in doc["rows"]]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise PortabilityError(f"cannot read portability results {f}: {e}") from e
        sources[doc["model_source"]] = {
            k: doc.get(k) for k in ("generated", "head", "models", "configurations", "models_glob")
        }
        if doc.get("generated", "") >= newest.get("generated", ""):
            newest = doc
    meta = {k: newest.get(k, "unknown") for k in ("generated", "head", "image", "digest")}
    return rows, {**meta, "sources": sources}
