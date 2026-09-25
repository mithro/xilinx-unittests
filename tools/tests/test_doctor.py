# SPDX-License-Identifier: Apache-2.0
"""Tests for `xut doctor` (tools/xut/doctor.py, spec §15): every external interaction
goes through a fake `Probe` here, so these tests never touch the network, docker, or
ssh."""

from click.testing import CliRunner

from xut.cli import main
from xut.container import SIM_IMAGE
from xut.doctor import Check, available_runners, run_checks
from xut.paths import VIVADO_SETTINGS


class FakeProbe:
    """Canned results for every `Probe` method, keyed the same way `doctor.py` calls
    them. Missing keys default to "everything succeeds" so a test only needs to
    override what it cares about."""

    def __init__(self, *, exists=None, which=None, command_ok=None, http_ok=None, images=None):
        self._images = images or {}
        self._exists = exists or {}
        self._which = which or {}
        self._command_ok = command_ok or {}
        self._http_ok = http_ok or {}

    def exists(self, path):
        return self._exists.get(str(path), True)

    def which(self, name):
        return self._which.get(name, f"/usr/bin/{name}")

    def command_ok(self, cmd, timeout):
        key = cmd[0]
        return self._command_ok.get(key, (True, f"{' '.join(cmd)}: ok"))

    def http_ok(self, url, timeout):
        return self._http_ok.get(url, (True, f"GET {url}: 200"))

    def image_digest(self, image):
        return self._images.get(image, "sha256:fake")


class RaisingProbe:
    """Every method raises, to prove `run_checks` never lets a broken probe crash it."""

    def exists(self, path):
        raise OSError("disk on fire")

    def which(self, name):
        raise OSError("disk on fire")

    def command_ok(self, cmd, timeout):
        raise TimeoutError("hung")

    def http_ok(self, url, timeout):
        raise TimeoutError("hung")

    def image_digest(self, image):
        raise OSError("docker on fire")


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


def test_all_checks_present_and_detail_non_empty():
    checks = run_checks(FakeProbe())
    names = {c.name for c in checks}
    assert names == {
        "vivado",
        "docker",
        "sim-container",
        "gh",
        "submodule",
        "docs",
        "pdftotext",
        "fpgas.online",
    }
    for c in checks:
        assert c.detail, f"{c.name} has an empty detail"


def test_all_ok_enables_every_runner():
    checks = run_checks(FakeProbe())
    assert all(c.ok for c in checks)
    runners = available_runners(checks)
    assert "xsim" in runners
    assert "vivado" in runners
    assert "iverilog" in runners
    assert "verilator" in runners
    assert "cocotb" not in runners  # a test style, not a runner (Ruling 23)
    assert "CI UNISIM" in runners
    assert "catalog" in runners
    assert "hw" in runners


def test_missing_vivado_removes_xsim_and_vivado_from_runners():
    probe = FakeProbe(exists={str(VIVADO_SETTINGS): False})
    checks = run_checks(probe)
    vivado = _by_name(checks)["vivado"]
    assert vivado.ok is False
    assert vivado.detail
    runners = available_runners(checks)
    assert "xsim" not in runners
    assert "vivado" not in runners
    # unrelated runners stay available
    assert "iverilog" in runners


def test_missing_submodule_marker_fails_and_does_not_enable_ci_unisim():
    class SubmoduleMissingProbe(FakeProbe):
        def exists(self, path):
            return "FDRE.v" not in str(path)

    checks = run_checks(SubmoduleMissingProbe())
    submodule = _by_name(checks)["submodule"]
    assert submodule.ok is False
    assert "FDRE.v" in submodule.detail
    assert "CI UNISIM" not in available_runners(checks)


def test_docker_command_failure_reported_not_raised():
    probe = FakeProbe(command_ok={"docker": (False, "docker info: exit 1")})
    checks = run_checks(probe)
    docker = _by_name(checks)["docker"]
    assert docker.ok is False
    assert docker.detail == "docker info: exit 1"
    runners = available_runners(checks)
    assert "iverilog" not in runners
    assert "verilator" not in runners


def test_docker_enables_nothing_itself():
    """The docker daemon alone runs nothing: the `sim-container` check (the built
    xut-sim image) carries the simulator runners. yosys/openxc7/vpr containers don't
    exist yet (a later step adds them). cocotb is a test style run inside those
    runners, not a runner (controller Ruling 23)."""
    checks = _by_name(run_checks(FakeProbe()))
    assert checks["docker"].enables == ()
    assert checks["sim-container"].enables == ("iverilog", "verilator")


def test_docker_ok_but_no_image_disables_simulators():
    probe = FakeProbe(images={SIM_IMAGE: None})
    checks = run_checks(probe)
    sim = _by_name(checks)["sim-container"]
    assert sim.ok is False
    assert "uv run xut container build" in sim.detail
    runners = available_runners(checks)
    assert "iverilog" not in runners
    assert "verilator" not in runners


def test_sim_container_detail_is_digest():
    sim = _by_name(run_checks(FakeProbe(images={SIM_IMAGE: "sha256:abc"})))["sim-container"]
    assert sim.ok is True
    assert "sha256:abc" in sim.detail


def test_docs_falls_back_to_http_when_pdf_missing():
    class DocsProbe(FakeProbe):
        def exists(self, path):
            return "ug953" not in str(path)

    probe = DocsProbe(http_ok={})
    checks = run_checks(probe)
    docs = _by_name(checks)["docs"]
    assert docs.ok is True
    assert "200" in docs.detail


def test_docs_fails_when_pdf_missing_and_http_fails():
    class DocsProbe(FakeProbe):
        def exists(self, path):
            return "ug953" not in str(path)

    url = "https://docs.amd.com/api/khub/maps/i4rliuWFec9CVaGVE8DYrg/attachments"
    probe = DocsProbe(http_ok={url: (False, "timed out")})
    checks = run_checks(probe)
    docs = _by_name(checks)["docs"]
    assert docs.ok is False
    assert "timed out" in docs.detail


def test_pdftotext_missing_reported_as_not_on_path():
    probe = FakeProbe(which={"pdftotext": None})
    checks = run_checks(probe)
    pdftotext = _by_name(checks)["pdftotext"]
    assert pdftotext.ok is False
    assert "PATH" in pdftotext.detail
    # "catalog" is still enabled by the (passing) docs check, so only when both
    # docs and pdftotext fail does "catalog" drop out of available_runners.
    assert "catalog" in available_runners(checks)


def test_catalog_runner_needs_both_docs_and_pdftotext():
    class BothMissingProbe(FakeProbe):
        def exists(self, path):
            return "ug953" not in str(path)

        def which(self, name):
            return None if name == "pdftotext" else super().which(name)

        def http_ok(self, url, timeout):
            return False, "no network"

    checks = run_checks(BothMissingProbe())
    assert "catalog" not in available_runners(checks)


def test_fpgas_online_uses_command_ok_with_ssh():
    calls = {}

    class SshProbe(FakeProbe):
        def command_ok(self, cmd, timeout):
            if cmd[0] == "ssh":
                calls["cmd"] = cmd
                calls["timeout"] = timeout
                return False, "ssh: exit 255 (Permission denied)"
            return super().command_ok(cmd, timeout)

    checks = run_checks(SshProbe())
    fpgas = _by_name(checks)["fpgas.online"]
    assert fpgas.ok is False
    assert fpgas.detail == "ssh: exit 255 (Permission denied)"
    assert calls["cmd"][0] == "ssh"
    assert "-p" in calls["cmd"]
    assert "10222" in calls["cmd"]
    assert "pi@ps1.fpgas.online" in calls["cmd"]
    # the subprocess timeout must exceed the ssh ConnectTimeout so the process can
    # never hang past the ssh client's own timeout.
    assert calls["timeout"] > 10


def test_raising_probe_never_crashes_run_checks():
    checks = run_checks(RaisingProbe())
    assert len(checks) == 8
    for c in checks:
        assert c.ok is False
        assert c.detail


def test_default_probe_used_when_none_given(monkeypatch):
    """`run_checks()` with no `probe` argument must construct and use `doctor.Probe` —
    never real subprocesses/network calls during this test. Monkeypatches the `Probe`
    name in `xut.doctor` with a fake class and asserts `run_checks` instantiated it."""
    instances = []

    class FakeDefaultProbe(FakeProbe):
        def __init__(self):
            super().__init__()
            instances.append(self)

    monkeypatch.setattr("xut.doctor.Probe", FakeDefaultProbe)
    checks = run_checks()
    assert len(instances) == 1
    assert len(checks) == 8
    for c in checks:
        assert c.detail
        assert c.ok is True


def test_doctor_cli_always_exits_zero(monkeypatch):
    """The CLI wires up the real `Probe` internally — patch it here too, so this stays
    hermetic (e.g. a CI checkout has no cached UG953 PDF, which would otherwise make
    the docs check fetch over the real network)."""
    monkeypatch.setattr("xut.doctor.Probe", FakeProbe)
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "available runners" in result.output
