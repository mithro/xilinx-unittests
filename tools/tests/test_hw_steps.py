# SPDX-License-Identifier: Apache-2.0
"""xut.hw.steps: the session layout and reply splitting, against the emulator."""

import pytest

from xut.hw import proto
from xut.hw.interp import EmuSlot, Harness
from xut.hw.selftest import CounterSim, PassthroughSim, selftest_programs
from xut.hw.steps import RUN_FRAME_LINES, Step, run_replies, session_steps, split_replies


def test_a_session_splits_into_one_reply_per_step():
    progs = selftest_programs()
    steps = session_steps(progs)
    assert [s.send[:1] for s in steps] == [b"I", b"L", b"R", b"L", b"R"]
    assert steps[2].lines == RUN_FRAME_LINES + len(progs[0].labels)
    emu = Harness(
        1,
        [EmuSlot(16, 16, 0, "0" * 16, PassthroughSim()), EmuSlot(2, 8, 1, "00", CounterSim())],
    )
    replies = split_replies(b"".join(emu.feed(s.send) for s in steps), steps)
    assert proto.parse_id(replies[0]).slots == 2
    runs = run_replies(replies, progs)
    assert sorted(runs) == [0, 1] and all(r.status == 0 for r in runs.values())
    assert len(runs[1].samples) == len(progs[1].labels)


def test_split_replies_refuses_truncated_and_trailing_bytes():
    steps = [Step(b"I", 1), Step(b"R", 2)]
    with pytest.raises(proto.ProtoError, match="truncated"):
        split_replies(b"a\nb\n", steps)
    with pytest.raises(proto.ProtoError, match="trailing"):
        split_replies(b"a\nb\nc\nd", steps)
    assert split_replies(b"a\nb\nc\n", steps) == [b"a\n", b"b\nc\n"]
