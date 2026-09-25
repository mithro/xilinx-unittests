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
"""

import os
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
    """Runs commands in `image`, with `root` (default: the repository) at `/work`."""

    def __init__(
        self,
        image: str = SIM_IMAGE,
        root: Path | None = None,
        mounts: tuple[Mount, ...] = (),
    ) -> None:
        self.image = image
        self.root = (root or repo_root()).resolve()
        self.mounts = mounts

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
            "--rm",
            "--name",
            name,
            "--network=none",
            "--pull=never",
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
        return p.returncode


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
    `tmp_path` -- is mounted read-write at `/xut-root`. The model mount comes first, so
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
