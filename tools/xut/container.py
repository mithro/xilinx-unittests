# SPDX-License-Identifier: Apache-2.0
"""Run simulator commands inside the pinned xut-sim container (or natively in CI).

`containers/sim/Dockerfile` builds the one simulator image (`SIM_IMAGE`). Every simulator
command goes through an `Executor`: `DockerExecutor` runs it in that image with
`--network=none` and `--pull=never` (a missing image is an error naming
`xut container build`, never a registry pull), as the invoking uid:gid, with the
repository at `/work` and model sources read-only under `/models/`. `NativeExecutor`
runs it on the host `PATH`; `executor_for` selects it when `XUT_NATIVE=1`, for an
environment that already provides the pinned tools. CI's `sim` job does not set it: it
builds the image and runs pytest on the host through `DockerExecutor`.

Every container is memory-capped (Ruling S48): `--memory=<m> --memory-swap=<m>`, where
`<m>` is `DockerExecutor(memory=...)`, else `$XUT_CONTAINER_MEMORY`, else `4g` (64m to
32g: docker reads 0 as no limit), and a command runs at most `max_jobs()` containers at
once: `$XUT_MEMORY_BUDGET` (default 100g) // the cap, 25 at the defaults. Rootful
docker puts containers outside the user's systemd slices, where systemd-oomd cannot see
them; the cap makes the kernel OOM-kill inside the container instead. `run` checks
`docker inspect`'s `State.OOMKilled` after every run and appends
`xut-container: oom-killed at memory cap <m>` to the log when it is set (the kernel may kill
a child, not the main process, so the exit code alone does not tell), then removes the
container itself (no `--rm`: the check needs the stopped container).
"""

import os
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from xut.errors import XutError
from xut.paths import repo_root

#: Bump whenever containers/sim/ changes.
SIM_IMAGE = "xut-sim:1"

#: How long `docker kill` may take after a timed-out run.
_KILL_TIMEOUT_S = 30

#: How long `docker inspect` / `docker rm -f` may take after a run.
_CLEANUP_TIMEOUT_S = 60

#: The per-container memory cap (Ruling S48), overridable by `XUT_CONTAINER_MEMORY`, and
#: its accepted range (S48a: docker reads 0 as "no limit"; below 6m it refuses to start).
DEFAULT_MEMORY = "4g"
MEMORY_ENV = "XUT_CONTAINER_MEMORY"
MEMORY_MIN, MEMORY_MAX = "64m", "32g"
#: The memory all of one command's containers may hold at once (S48a), overridable by
#: `XUT_MEMORY_BUDGET`: a command runs at most budget // cap containers (`max_jobs`).
DEFAULT_BUDGET = "100g"
BUDGET_ENV = "XUT_MEMORY_BUDGET"
_SIZE_RE = re.compile(r"([0-9]+)([kmg])")
_UNIT = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}

#: The start of the line `run` appends to the log when the container was OOM-killed.
OOM_MARK = "xut-container: oom-killed"


def size_bytes(value: str, what: str, hi: str | None = None) -> int:
    """``value`` (``<digits><k|m|g>``) in bytes; ``XutError`` (naming ``what``) unless it
    is at least ``MEMORY_MIN`` and, with ``hi``, at most ``hi``."""
    m = _SIZE_RE.fullmatch(value)
    rng = f"{MEMORY_MIN} to {hi}" if hi else f"at least {MEMORY_MIN}"
    if m is None:
        raise XutError(f"{what}={value!r} is not <digits><k|m|g> ({rng}, e.g. 4g)")
    n = int(m.group(1)) * _UNIT[m.group(2)]
    lo_b = int(MEMORY_MIN[:-1]) * _UNIT[MEMORY_MIN[-1]]
    hi_b = int(hi[:-1]) * _UNIT[hi[-1]] if hi else None
    if n < lo_b or (hi_b is not None and n > hi_b):
        raise XutError(f"{what}={value!r} is out of range: it must be {rng}")
    return n


def container_memory(memory: str | None = None) -> str:
    """The container memory cap: ``memory``, else ``$XUT_CONTAINER_MEMORY``, else ``4g``;
    ``XutError`` outside ``MEMORY_MIN``..``MEMORY_MAX``."""
    if memory is None:
        memory, what = os.environ.get(MEMORY_ENV, DEFAULT_MEMORY), f"${MEMORY_ENV}"
    else:
        what = "container memory cap"
    size_bytes(memory, what, MEMORY_MAX)
    return memory


def max_jobs() -> tuple[int, str, str]:
    """(the most containers one command may run at once, the budget, the cap): the memory
    budget (``$XUT_MEMORY_BUDGET``, else ``100g``) // the container cap (S48a)."""
    cap = container_memory()
    budget = os.environ.get(BUDGET_ENV, DEFAULT_BUDGET)
    n = size_bytes(budget, f"${BUDGET_ENV}") // size_bytes(cap, f"${MEMORY_ENV}", MEMORY_MAX)
    return n, budget, cap


def oom_line(memory: str) -> str:
    return f"{OOM_MARK} at memory cap {memory}"


class RunTimeout(RuntimeError):
    """A simulator command exceeded its `timeout_s`."""


class ContainerError(XutError, RuntimeError):
    """The simulator image is missing or a tool in it did not run."""


@dataclass(frozen=True)
class Mount:
    host: Path
    guest: str
    ro: bool = True


class Executor(Protocol):
    def run(
        self,
        argv: list[str],
        cwd: Path,
        log: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> int:
        """Run `argv` in `cwd`, appending its stdout+stderr to `log`; return the exit
        code. Raises `RunTimeout` after `timeout_s` seconds."""
        ...

    def guest(self, path: Path) -> str:
        """`path` as the command sees it."""
        ...


def _append(log: Path) -> TextIO:
    log.parent.mkdir(parents=True, exist_ok=True)
    return log.open("a")


class NativeExecutor:
    """Tools on the host PATH (selected by `executor_for` when XUT_NATIVE=1)."""

    def guest(self, path: Path) -> str:
        return str(path)

    def run(
        self,
        argv: list[str],
        cwd: Path,
        log: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> int:
        with _append(log) as f:
            f.write(f"$ {' '.join(argv)}\n")
            f.flush()
            try:
                p = subprocess.run(
                    argv,
                    cwd=cwd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_s,
                    env={**os.environ, **(env or {})},
                )
            except subprocess.TimeoutExpired as e:
                raise RunTimeout(f"timeout after {timeout_s}s: {argv[0]}") from e
        return p.returncode


class DockerExecutor:
    """Runs commands in `image`, with `root` (default: the repository) at `/work`, capped
    at `memory` (default: `$XUT_CONTAINER_MEMORY`, else `4g`)."""

    def __init__(
        self,
        image: str = SIM_IMAGE,
        root: Path | None = None,
        mounts: tuple[Mount, ...] = (),
        memory: str | None = None,
    ) -> None:
        self.image = image
        self.root = (root or repo_root()).resolve()
        self.mounts = mounts
        self.memory = container_memory(memory)

    def guest(self, path: Path) -> str:
        p = Path(path).resolve()
        if p.is_relative_to(self.root):
            return "/work" if p == self.root else f"/work/{p.relative_to(self.root)}"
        for m in self.mounts:
            if p.is_relative_to(m.host):
                rel = p.relative_to(m.host)
                return m.guest if str(rel) == "." else f"{m.guest}/{rel}"
        raise ValueError(f"{p} is not visible in the container (mount it first)")

    def argv(self, argv: list[str], cwd: Path, name: str, env: dict[str, str] | None) -> list[str]:
        """The full `docker run` command line for `argv`."""
        out = [
            "docker",
            "run",
            "--name",
            name,
            "--network=none",
            "--pull=never",
            f"--memory={self.memory}",
            f"--memory-swap={self.memory}",
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{self.root}:/work",
        ]
        for m in self.mounts:
            out += ["-v", f"{m.host}:{m.guest}{':ro' if m.ro else ''}"]
        for k, v in (env or {}).items():
            out += ["-e", f"{k}={v}"]
        out += ["-w", self.guest(cwd), self.image, *argv]
        return out

    def run(
        self,
        argv: list[str],
        cwd: Path,
        log: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> int:
        name = f"xut-{uuid.uuid4().hex[:12]}"
        full = self.argv(argv, Path(cwd), name, env)
        with _append(log) as f:
            f.write(f"$ {' '.join(argv)}   [container {self.image} {name}]\n")
            f.flush()
            try:
                p = subprocess.run(full, stdout=f, stderr=subprocess.STDOUT, timeout=timeout_s)
            except subprocess.TimeoutExpired as e:
                # Killing the `docker run` client does not stop the container; kill it.
                try:
                    subprocess.run(
                        ["docker", "kill", name],
                        stdout=f,
                        stderr=subprocess.STDOUT,
                        timeout=_KILL_TIMEOUT_S,
                    )
                except subprocess.TimeoutExpired as k:
                    raise RunTimeout(
                        f"timeout after {timeout_s}s: {argv[0]}; docker kill {name} also "
                        f"timed out after {_KILL_TIMEOUT_S}s (the container may still run)"
                    ) from k
                raise RunTimeout(f"timeout after {timeout_s}s: {argv[0]}") from e
            finally:
                # Every path (a result, a timeout, an exception): record an OOM kill, then
                # remove the container (no --rm: the check needs it stopped, not gone).
                self._finish(name, f)
        return p.returncode

    def _finish(self, name: str, f: TextIO) -> None:
        """Append the OOM line to `f` if container `name` was OOM-killed, then remove it.
        A failure of either step is logged, never raised: it must not mask the run's own
        result or exception."""
        try:
            q = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.OOMKilled}}", name],
                capture_output=True,
                text=True,
                timeout=_CLEANUP_TIMEOUT_S,
            )
            if q.returncode == 0 and (q.stdout or "").strip() == "true":
                f.write(oom_line(self.memory) + "\n")
        except (OSError, subprocess.SubprocessError) as e:
            f.write(f"xut-container: docker inspect {name} failed: {e}\n")
        try:
            r = subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                text=True,
                timeout=_CLEANUP_TIMEOUT_S,
            )
            if r.returncode != 0 and "No such container" not in (r.stderr or ""):
                f.write(f"xut-container: docker rm -f {name} failed: {(r.stderr or '').strip()}\n")
        except (OSError, subprocess.SubprocessError) as e:
            f.write(f"xut-container: docker rm -f {name} failed: {e}\n")
        f.flush()


class _HasModelSrc(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def src(self) -> Path: ...


def executor_for(model_source: _HasModelSrc, work_root: Path | None = None) -> Executor:
    """The executor for runs against `model_source` (an `xut.modelsrc.ModelSource`).

    `XUT_NATIVE=1` selects `NativeExecutor`. Otherwise a model source outside the
    repository (the Vivado install) is mounted read-only at `/models/<name>`, and a
    `work_root` (the run's `RunContext.root`) outside the repository -- a pytest
    `tmp_path` -- is mounted READ-WRITE at `/xut-root`. `/`, `$HOME` and any ancestor
    of the repository are refused as a work root (`ContainerError`): the container
    would get write access to far more than one run's directory. The model mount comes first, so
    a model source inside that root still resolves to its read-only mount."""
    if os.environ.get("XUT_NATIVE") == "1":
        return NativeExecutor()
    repo = repo_root().resolve()
    src = model_source.src.resolve()
    mounts: tuple[Mount, ...] = ()
    if not src.is_relative_to(repo):
        mounts = (Mount(src, f"/models/{model_source.name}"),)
    if work_root is not None:
        w = Path(work_root).resolve()
        if not w.is_relative_to(repo):
            # Mounted READ-WRITE (the runs write there): never a broad directory.
            if w == Path(w.anchor) or w == Path.home().resolve() or repo.is_relative_to(w):
                raise ContainerError(
                    f"refusing to mount run root {w} read-write in the container: it is "
                    "/, $HOME or an ancestor of the repository; use a dedicated directory"
                )
            mounts += (Mount(w, "/xut-root", ro=False),)
    return DockerExecutor(mounts=mounts)


def image_digest(image: str = SIM_IMAGE) -> str | None:
    """The local image ID of `image`, or None if it is not built (or docker is absent)."""
    try:
        p = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


_VERSIONS: dict[str, dict[str, str]] = {}
_VERSIONS_LOCK = threading.Lock()

#: (key, argv, banner prefix or None). `iverilog -V` exits non-zero without a source
#: file, so its exit code is not checked; its banner is.
_TOOLS = (
    ("iverilog", ["iverilog", "-V"], "Icarus Verilog version "),
    ("verilator", ["verilator", "--version"], None),
    ("cocotb", ["cocotb-config", "--version"], None),
)


def sim_tool_versions(ex: Executor, workdir: Path) -> dict[str, str]:
    """First line of each tool's version output (recorded in result.json).

    Computed once per process and image, under a lock, with a private log file: runner
    jobs are threads (xut run --jobs N), so a shared log file would race (review #9).
    A missing image, a non-zero exit or a missing banner raises `ContainerError`
    (review A3): an error message is never recorded, or cached, as a version."""
    key_img = getattr(ex, "image", "native")
    with _VERSIONS_LOCK:
        if key_img in _VERSIONS:
            return dict(_VERSIONS[key_img])
        if isinstance(ex, DockerExecutor) and image_digest(ex.image) is None:
            raise ContainerError(
                f"{ex.image} is not built (or docker is unavailable): "
                "run `uv run xut container build`"
            )
        workdir.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {}
        for key, argv, banner in _TOOLS:
            log = workdir / f".versions-{uuid.uuid4().hex}.log"
            try:
                rc = ex.run(argv, cwd=workdir, log=log, timeout_s=60)
                # Line 0 is the executor's own "$ <argv>" header.
                lines = [ln.strip() for ln in log.read_text().splitlines()[1:] if ln.strip()]
            finally:
                log.unlink(missing_ok=True)
            first = lines[0] if lines else ""
            bad = not first.startswith(banner) if banner else rc != 0 or not first
            if bad:
                raise ContainerError(
                    f"{key}: `{' '.join(argv)}` failed in {key_img} (exit {rc}): "
                    f"{' | '.join(lines[:3]) or '(no output)'}; if the image is missing, "
                    "run `uv run xut container build`"
                )
            out[key] = first
        _VERSIONS[key_img] = out
        return dict(out)
