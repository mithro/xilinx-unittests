# SPDX-License-Identifier: Apache-2.0
"""xut.slots: the host-wide Vivado slot limiter (PR #10 CQ2), on private lock dirs."""

import threading
import time
from pathlib import Path

import pytest

from xut import slots
from xut.errors import XutError


def test_slots_are_taken_in_order_and_released(tmp_path):
    with slots.vivado_slot(2, tmp_path) as a, slots.vivado_slot(2, tmp_path) as b:
        assert (a, b) == (0, 1)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["slot0.lock", "slot1.lock"]
    with slots.vivado_slot(2, tmp_path) as c:
        assert c == 0  # released on exit


def test_a_full_set_of_slots_waits_until_one_is_free(tmp_path):
    got: list[int] = []
    lines: list[str] = []
    with slots.vivado_slot(1, tmp_path):
        t = threading.Thread(
            target=lambda: got.append(
                slots.vivado_slot(1, tmp_path, poll_s=0.01, log=lines.append).__enter__()
            )
        )
        t.start()
        time.sleep(0.1)
        assert got == [] and t.is_alive()  # waiting on the held slot
    t.join(timeout=5)
    assert got == [0]
    assert lines == [f"vivado_slot: all 1 slots in {tmp_path} are busy; waiting"]


def test_at_most_n_bodies_run_at_once(tmp_path):
    active, peak, lock = 0, 0, threading.Lock()

    def body() -> None:
        nonlocal active, peak
        with slots.vivado_slot(3, tmp_path, poll_s=0.005):
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1

    threads = [threading.Thread(target=body) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert peak == 3 and active == 0


def test_slot_count_and_dir_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv(slots.SLOTS_ENV, raising=False)
    assert slots.slot_count() == 4
    monkeypatch.setenv(slots.SLOTS_ENV, "2")
    assert slots.slot_count() == 2
    for bad in ("0", "-1", "many"):
        monkeypatch.setenv(slots.SLOTS_ENV, bad)
        with pytest.raises(XutError, match="not a positive integer"):
            slots.slot_count()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert slots.slot_dir() == tmp_path / "xut-vivado"
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert slots.slot_dir().name == "xut-vivado"


def test_every_host_xsim_run_holds_a_slot(tmp_path, monkeypatch):
    """xsim.run_script (the xsim runner and the equivalence oracle) runs inside a slot."""
    from xut.runners import xsim

    held: list[bool] = []
    real = slots.vivado_slot

    def spy(*a, **kw):
        held.append(True)
        return real(1, tmp_path / "locks")

    monkeypatch.setattr(slots, "vivado_slot", spy)
    (tmp_path / "xsim.sh").write_text("echo ran\nexit 3\n")
    assert xsim.run_script(tmp_path, 30) == 3
    assert held == [True] and (tmp_path / "run.log").read_text() == "ran\n"
    assert Path(tmp_path / "locks" / "slot0.lock").is_file()
