# SPDX-License-Identifier: Apache-2.0
"""Run simulator commands inside the pinned xut-sim container (or natively in CI).

`containers/sim/Dockerfile` builds the one simulator image (`SIM_IMAGE`). Every simulator
command goes through an `Executor`: `DockerExecutor` runs it in that image with
`--network=none`, as the invoking uid:gid, with the repository at `/work` and model
sources read-only under `/models/`; `NativeExecutor` runs it on the host `PATH` (CI's
`sim` job sets `XUT_NATIVE=1` when it already runs inside the image).
"""

import os
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from xut.paths import repo_root

#: Bump whenever containers/sim/ changes.
SIM_IMAGE = "xut-sim:1"

#: How long `docker kill` may take after a timed-out run.
_KILL_TIMEOUT_S = 30


class RunTimeout(RuntimeError):
    """A simulator command exceeded its `timeout_s`."""


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
    """Tools on PATH (used inside CI's xut-sim job, where XUT_NATIVE=1)."""

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
                subprocess.run(
                    ["docker", "kill", name],
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=_KILL_TIMEOUT_S,
                )
                raise RunTimeout(f"timeout after {timeout_s}s: {argv[0]}") from e
        return p.returncode


class _HasModelSrc(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def src(self) -> Path: ...


def executor_for(model_source: _HasModelSrc) -> Executor:
    """The executor for runs against `model_source` (an `xut.modelsrc.ModelSource`).

    `XUT_NATIVE=1` selects `NativeExecutor`. Otherwise a model source outside the
    repository (the Vivado install) is mounted read-only at `/models/<name>`."""
    if os.environ.get("XUT_NATIVE") == "1":
        return NativeExecutor()
    src = model_source.src.resolve()
    mounts: tuple[Mount, ...] = ()
    if not src.is_relative_to(repo_root().resolve()):
        mounts = (Mount(src, f"/models/{model_source.name}"),)
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


def sim_tool_versions(ex: Executor, workdir: Path) -> dict[str, str]:
    """First line of each tool's version output (recorded in result.json).

    Computed once per process and image, under a lock, with a private log file: runner
    jobs are threads (xut run --jobs N), so a shared log file would race (review #9)."""
    key_img = getattr(ex, "image", "native")
    with _VERSIONS_LOCK:
        if key_img in _VERSIONS:
            return dict(_VERSIONS[key_img])
        workdir.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {}
        for key, argv in (
            ("iverilog", ["iverilog", "-V"]),
            ("verilator", ["verilator", "--version"]),
            ("cocotb", ["cocotb-config", "--version"]),
        ):
            log = workdir / f".versions-{uuid.uuid4().hex}.log"
            try:
                # `iverilog -V` exits non-zero without a source file; only the banner matters.
                ex.run(argv, cwd=workdir, log=log, timeout_s=60)
                # Line 0 is the executor's own "$ <argv>" header.
                lines = [ln for ln in log.read_text().splitlines()[1:] if ln.strip()]
            finally:
                log.unlink(missing_ok=True)
            out[key] = lines[0].strip() if lines else "unknown"
        _VERSIONS[key_img] = out
        return dict(out)
