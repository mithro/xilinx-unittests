# SPDX-License-Identifier: Apache-2.0
"""The host's side of one harness session, independent of how the bytes travel
(simulation testbench, UART on a rig, the emulator). Standard library only.

A session is ``I``, then per slot in slot order ``L`` (one reply line) and ``R`` (the run
line, one line per sample, the end line). ``slot_replies`` owns that indexing; the
simulator, the board session and the tests all use it rather than re-deriving it.

**One command in flight** (``xut.hw.proto``). A ``Step`` is one command and the number
of lines of its reply. Whatever carries the bytes sends a step's ``send`` only after
every line of the previous step's reply has arrived (for ``R``, through the ``end``
line): the RTL has no receive FIFO and discards any byte that arrives while it replies
or runs, and the emulator (``xut.hw.interp.Harness``) raises ``EmuError`` on one. The
simulation testbench waits on the cumulative line count (``xut.hw.hwsim.render_host``);
the emulator is fed one step per ``feed`` call.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from xut.hw import proto
from xut.hw.image import HwProgram

#: Lines in an ``R`` reply besides its samples: the run line and the end line.
RUN_FRAME_LINES = 2


@dataclass(frozen=True)
class Step:
    send: bytes
    lines: int  # the lines of the harness's reply


def session_steps(programs: dict[int, HwProgram]) -> list[Step]:
    """``I``, then per slot in order: ``L`` (one line) and ``R`` (run, samples, end)."""
    steps = [Step(proto.CMD_ID, 1)]
    for slot, p in sorted(programs.items()):
        steps.append(Step(proto.load_frame(slot, p.words), 1))
        steps.append(Step(proto.CMD_RUN, RUN_FRAME_LINES + len(p.labels)))
    return steps


def split_replies(data: bytes, steps: Sequence[Step]) -> list[bytes]:
    """``data`` cut into one reply per step by line counts; leftovers are an error."""
    out, pos = [], 0
    for s in steps:
        end = pos
        for _ in range(s.lines):
            j = data.find(b"\n", end)
            if j < 0:
                raise proto.ProtoError(f"reply to {s.send[:1]!r} truncated: {data[pos:][:80]!r}")
            end = j + 1
        out.append(data[pos:end])
        pos = end
    if pos != len(data):
        raise proto.ProtoError(
            f"{len(data) - pos} unexpected trailing byte(s): {data[pos:][:80]!r}"
        )
    return out


def slot_replies(replies: Sequence[bytes], slots: Iterable[int]) -> dict[int, tuple[bytes, bytes]]:
    """The raw ``(L reply, R reply)`` per slot of a ``session_steps`` session."""
    return {s: (replies[1 + 2 * k], replies[2 + 2 * k]) for k, s in enumerate(sorted(slots))}


def run_replies(replies: Sequence[bytes], slots: Iterable[int]) -> dict[int, proto.RunReply]:
    """The parsed ``R`` reply per slot."""
    return {s: proto.parse_run(run) for s, (_, run) in slot_replies(replies, slots).items()}
