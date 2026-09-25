# SPDX-License-Identifier: Apache-2.0
"""`xut doctor`: preflight checks (spec §15).

Every external interaction (file existence, running a command, an HTTP request) goes
through a `Probe`, so tests can swap in a fake and never touch the network, docker, or
ssh. `run_checks()` never raises: a probe method that raises or hangs is treated as that
one check failing, with the error as its detail — `doctor` always has something useful
to report and always exits 0 (it is informational, not a gate).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import requests

from xut.docs_fetch import API, UG953
from xut.paths import VIVADO_SETTINGS, cache_dir, submodule_unisim

#: fpgas.online SSH coordinates. TODO: read these from `hw/boards/fpgas_online.yaml`
#: once that file exists (not yet created as of step 1 bootstrap; see task-9 brief).
FPGAS_ONLINE_HOST = "ps1.fpgas.online"
FPGAS_ONLINE_PORT = 10222
FPGAS_ONLINE_USER = "pi"

#: `ssh -o ConnectTimeout=...` for the fpgas.online reachability probe.
_SSH_CONNECT_TIMEOUT = 10
#: Subprocess-level timeout, kept a little above `_SSH_CONNECT_TIMEOUT` so a hung ssh
#: client (e.g. stuck on a host-key prompt despite BatchMode) can never block `doctor`.
_SSH_SUBPROCESS_TIMEOUT = 15
#: Timeout for the docs.amd.com HEAD/GET fallback check (task-9 brief).
_DOCS_HTTP_TIMEOUT = 15


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    enables: tuple[str, ...] = ()


class Probe:
    """Real implementations of every external interaction a check performs."""

    def exists(self, path: Path) -> bool:
        return Path(path).exists()

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def command_ok(self, cmd: Sequence[str], timeout: float) -> tuple[bool, str]:
        """Run `cmd`; return `(ok, detail)`. Never raises: a missing binary or a
        timeout is reported as `(False, ...)`, not an exception."""
        rendered = " ".join(cmd)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return False, f"{cmd[0]}: command not found"
        except subprocess.TimeoutExpired:
            return False, f"{rendered}: timed out after {timeout}s"
        if proc.returncode == 0:
            return True, f"{rendered}: ok"
        stderr_lines = proc.stderr.strip().splitlines()
        tail = f" ({stderr_lines[-1]})" if stderr_lines else ""
        return False, f"{rendered}: exit {proc.returncode}{tail}"

    def http_ok(self, url: str, timeout: float) -> tuple[bool, str]:
        """HEAD `url`, falling back to GET if HEAD isn't 200; return `(ok, detail)`.
        Never raises: a connection error or timeout is reported as `(False, ...)`."""
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                return True, f"HEAD {url}: 200"
            r = requests.get(url, timeout=timeout, stream=True)
            return r.status_code == 200, f"GET {url}: {r.status_code}"
        except requests.RequestException as e:
            return False, f"{url}: {e}"


def _safe(name: str, enables: tuple[str, ...], fn: Callable[[], tuple[bool, str]]) -> Check:
    """Run one check's `fn`, turning any exception into a failing `Check` rather than
    letting it propagate — a broken or misbehaving probe must never crash `doctor`."""
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 - a probe must never crash doctor
        ok, detail = False, f"{type(e).__name__}: {e}"
    return Check(name, ok, detail, enables)


def _check_vivado(probe: Probe) -> tuple[bool, str]:
    ok = probe.exists(VIVADO_SETTINGS)
    return ok, f"{VIVADO_SETTINGS} " + ("exists" if ok else "not found")


def _check_docker(probe: Probe) -> tuple[bool, str]:
    return probe.command_ok(["docker", "info"], timeout=10)


def _check_gh(probe: Probe) -> tuple[bool, str]:
    return probe.command_ok(["gh", "auth", "status"], timeout=10)


def _check_submodule(probe: Probe) -> tuple[bool, str]:
    marker = submodule_unisim() / "FDRE.v"
    ok = probe.exists(marker)
    detail = f"{marker} exists" if ok else f"{marker} not found (git submodule update --init)"
    return ok, detail


def _check_docs(probe: Probe) -> tuple[bool, str]:
    pdf = cache_dir() / "docs" / UG953.pdf_name
    if probe.exists(pdf):
        return True, f"{pdf} exists"
    url = f"{API}/{UG953.map_id}/attachments"
    ok, http_detail = probe.http_ok(url, timeout=_DOCS_HTTP_TIMEOUT)
    return ok, f"{pdf} not found; {http_detail}"


def _check_pdftotext(probe: Probe) -> tuple[bool, str]:
    found = probe.which("pdftotext")
    return found is not None, found or "pdftotext not found on PATH"


def _check_fpgas_online(probe: Probe) -> tuple[bool, str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={_SSH_CONNECT_TIMEOUT}",
        "-p",
        str(FPGAS_ONLINE_PORT),
        f"{FPGAS_ONLINE_USER}@{FPGAS_ONLINE_HOST}",
        "true",
    ]
    return probe.command_ok(cmd, timeout=_SSH_SUBPROCESS_TIMEOUT)


def run_checks(probe: Probe | None = None) -> list[Check]:
    """Run every preflight check, in the order of the task-9 brief's table.

    `docker` only enables `iverilog` and `verilator` — spec rev 3.1's runner
    vocabulary (controller ruling). cocotb is a test *style* run inside those
    runners, not a runner itself. The yosys, `openxc7` (yosys + openXC7 nextpnr +
    prjxray) and `vpr` (F4PGA/VPR) flow containers don't exist yet; later steps add
    their own checks once they do.
    """
    p = probe or Probe()
    return [
        _safe("vivado", ("xsim", "vivado"), lambda: _check_vivado(p)),
        _safe("docker", ("iverilog", "verilator"), lambda: _check_docker(p)),
        _safe("gh", (), lambda: _check_gh(p)),
        _safe("submodule", ("CI UNISIM",), lambda: _check_submodule(p)),
        _safe("docs", ("catalog",), lambda: _check_docs(p)),
        _safe("pdftotext", ("catalog",), lambda: _check_pdftotext(p)),
        _safe("fpgas.online", ("hw",), lambda: _check_fpgas_online(p)),
    ]


def available_runners(checks: list[Check]) -> list[str]:
    """The sorted, de-duplicated union of `enables` across every passing check."""
    return sorted({r for c in checks if c.ok for r in c.enables})
