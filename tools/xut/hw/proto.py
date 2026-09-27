# SPDX-License-Identifier: Apache-2.0
"""The stepped harness's UART protocol (spec §7.1 "UART dumper"). Standard library only:
the host (xut.hw.session), the reference emulator (xut.hw.interp) and the generator of
the harness's message ROM (``tools/xut/hdl/hw/xut_hw_msgs.vh``) all use this module.

Host -> harness, raw bytes::

    "I"                                    identify
    "L" slot:u8 nwords:u16le word:u32le*nwords crc:u32le
                                           load one slot's program; crc = zlib.crc32 of
                                           the bytes from slot through the last word
    "R"                                    run the loaded program on the loaded slot

Harness -> host: ASCII lines ending in "\\n" (``MESSAGES``); every number is fixed-width
lower-case hex. A run answers with a ``run`` line, one ``sample`` line per SAMPLE and an
``end`` line whose ``crc`` is zlib.crc32 of every byte from the ``run`` line's ``#``
through the ``\\n`` before the ``end`` line. The harness streams raw samples (``S <n>
<out_vec bits>``), not ``.xtr``: port names live in the wrapper's map, which the host
applies (``xut.hw.replay.samples_to_trace``).

The same templates generate the harness's message ROM (``render_rom_vh``), so the host
parser, the emulator and the RTL cannot drift apart.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass

PROTO = 1
CMD_ID, CMD_LOAD, CMD_RUN = b"I", b"L", b"R"

STATUS = {
    0: "ok",
    1: "used",  # the slot already ran since the FPGA was configured
    2: "noload",  # R without a successful L
    3: "badop",  # an unknown opcode, or the program ran past its last word
    4: "badslot",  # L named a slot the bitstream does not have
    5: "badcrc",  # L's CRC did not match the bytes received
    6: "toolong",  # L with 0 words or more than the harness's maxwords
    7: "badcmd",  # an unknown command byte
}
STATUS_CODE = {v: k for k, v in STATUS.items()}

#: field -> (ROM token, hex digits). ``bits`` is binary: max(1, nout) chars of 0/1.
FIELDS: dict[str, tuple[int, int]] = {
    "build": (0x81, 8),
    "slots": (0x82, 2),
    "maxwords": (0x83, 4),
    "margin": (0x84, 2),
    "slot": (0x85, 2),
    "words": (0x86, 4),
    "crc": (0x87, 8),
    "status": (0x88, 2),
    "samples": (0x89, 4),
    "sidx": (0x8A, 4),
    "bits": (0x8B, 0),
    "cmd": (0x8C, 2),
}
#: message -> template. The dict order is the ROM's message numbering (XUT_MSG_*).
MESSAGES: dict[str, str] = {
    "id": "# xut-hw 1 id build={build} slots={slots} maxwords={maxwords} margin={margin}\n",
    "load": "# xut-hw 1 load slot={slot} words={words} crc={crc} status={status}\n",
    "run": "# xut-hw 1 run build={build} slot={slot} words={words}\n",
    "sample": "S {sidx} {bits}\n",
    "end": "# xut-hw 1 end slot={slot} samples={samples} status={status} crc={crc}\n",
    "err": "# xut-hw 1 err cmd={cmd} status={status}\n",
}
_FIELD = re.compile(r"\{(\w+)\}")
ROM_SIZE = 512  # the printer's 9-bit ROM address


class ProtoError(ValueError):
    """A reply that is malformed, truncated or fails its CRC. For the host this is a
    transport error (retried once, spec §7.5)."""


def render(name: str, **values: int | str) -> bytes:
    """Message ``name`` exactly as the RTL prints it."""

    def sub(m: re.Match[str]) -> str:
        f = m.group(1)
        if f == "bits":
            bits = str(values["bits"])
            if not bits or set(bits) - {"0", "1"}:
                raise ProtoError(f"bits {bits!r} must be one or more 0/1")
            return bits
        digits = FIELDS[f][1]
        v = int(values[f])
        if not 0 <= v < 16**digits:
            raise ProtoError(f"{f}={v} does not fit {digits} hex digits")
        return f"{v:0{digits}x}"

    return _FIELD.sub(sub, MESSAGES[name]).encode("ascii")


def _pattern(name: str) -> re.Pattern[str]:
    tpl, out, pos = MESSAGES[name], [], 0
    for m in _FIELD.finditer(tpl):
        out.append(re.escape(tpl[pos : m.start()]))
        f = m.group(1)
        out.append(f"(?P<{f}>[01]+)" if f == "bits" else f"(?P<{f}>[0-9a-f]{{{FIELDS[f][1]}}})")
        pos = m.end()
    out.append(re.escape(tpl[pos:]))
    return re.compile("".join(out))


PATTERNS = {n: _pattern(n) for n in MESSAGES}


def parse(name: str, line: bytes) -> dict[str, int | str]:
    """The fields of one ``name`` line (with its ``\\n``); hex fields as ints."""
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError as e:
        raise ProtoError(f"expected a {name} line, got non-ASCII bytes {line[:60]!r}") from e
    m = PATTERNS[name].fullmatch(text)
    if not m:
        raise ProtoError(f"expected a {name} line, got {text[:120]!r}")
    return {k: (v if k == "bits" else int(v, 16)) for k, v in m.groupdict().items()}


@dataclass(frozen=True)
class IdReply:
    build: int
    slots: int
    maxwords: int
    margin: int


@dataclass(frozen=True)
class LoadReply:
    slot: int
    words: int
    crc: int
    status: int


@dataclass(frozen=True)
class RunReply:
    build: int
    slot: int
    words: int
    samples: tuple[str, ...]
    status: int
    crc: int


def load_frame(slot: int, words: Sequence[int]) -> bytes:
    """The ``L`` command for ``words`` into ``slot``."""
    if not 0 <= slot < 256:
        raise ProtoError(f"slot {slot} is not 0..255")
    if not 0 < len(words) < 1 << 16:
        raise ProtoError(f"{len(words)} words: a load carries 1..65535")
    if any(not 0 <= w < 1 << 32 for w in words):
        raise ProtoError("a program word is not 32 bits")
    body = struct.pack("<BH", slot, len(words)) + b"".join(struct.pack("<I", w) for w in words)
    return CMD_LOAD + body + struct.pack("<I", zlib.crc32(body))


def _lines(data: bytes) -> list[bytes]:
    if not data.endswith(b"\n"):
        raise ProtoError(f"truncated reply (no final newline): {data[-60:]!r}")
    return [ln + b"\n" for ln in data[:-1].split(b"\n")]


def parse_id(data: bytes) -> IdReply:
    (line,) = _one(data)
    return IdReply(**parse("id", line))  # type: ignore[arg-type]


def parse_load(data: bytes) -> LoadReply:
    (line,) = _one(data)
    return LoadReply(**parse("load", line))  # type: ignore[arg-type]


def _one(data: bytes) -> list[bytes]:
    lines = _lines(data)
    if len(lines) != 1:
        raise ProtoError(f"expected one line, got {len(lines)}: {data[:120]!r}")
    return lines


def parse_run(data: bytes) -> RunReply:
    """A whole ``R`` reply: header, samples in order, end line with a matching CRC."""
    lines = _lines(data)
    if len(lines) < 2:
        raise ProtoError(f"run reply has {len(lines)} line(s): {data[:120]!r}")
    head, end = parse("run", lines[0]), parse("end", lines[-1])
    samples = []
    for i, ln in enumerate(lines[1:-1]):
        s = parse("sample", ln)
        if s["sidx"] != i:
            raise ProtoError(f"sample {s['sidx']} out of order (expected {i})")
        samples.append(str(s["bits"]))
    calc = zlib.crc32(b"".join(lines[:-1]))
    if calc != end["crc"]:
        raise ProtoError(f"run CRC {end['crc']:08x} does not match the bytes ({calc:08x})")
    if end["samples"] != len(samples) or end["slot"] != head["slot"]:
        raise ProtoError(f"end line {end} does not match the {len(samples)} samples received")
    return RunReply(
        int(head["build"]),
        int(head["slot"]),
        int(head["words"]),
        tuple(samples),
        int(end["status"]),
        int(end["crc"]),
    )


def rom() -> tuple[list[int], dict[str, int]]:
    """The message ROM: each template as ASCII bytes with a field's token in place of
    the field, ended by 0x00; plus each message's start address."""
    data: list[int] = []
    start: dict[str, int] = {}
    for name, tpl in MESSAGES.items():
        start[name] = len(data)
        pos = 0
        for m in _FIELD.finditer(tpl):
            data += list(tpl[pos : m.start()].encode("ascii"))
            data.append(FIELDS[m.group(1)][0])
            pos = m.end()
        data += [*tpl[pos:].encode("ascii"), 0]
    if len(data) > ROM_SIZE:
        raise ProtoError(f"message ROM is {len(data)} bytes; the printer addresses {ROM_SIZE}")
    return data, start


def render_rom_vh() -> str:
    """``xut_hw_msgs.vh``: message numbers, field tokens, field widths and the ROM, as
    localparams and functions for inclusion inside a module."""
    data, start = rom()
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// GENERATED by `uv run xut hw gen-rtl` from xut.hw.proto.MESSAGES. Do not edit.",
        f"// Message ROM: {len(data)} bytes.",
    ]
    for i, name in enumerate(MESSAGES):
        out.append(f"localparam [2:0] XUT_MSG_{name.upper()} = 3'd{i};")
    for name, (tok, _) in FIELDS.items():
        out.append(f"localparam [3:0] XUT_F_{name.upper()} = 4'h{tok & 0xF:x};")
    out += ["function [8:0] xut_hw_msg_start(input [2:0] msg);", "  case (msg)"]
    out += [f"    3'd{i}: xut_hw_msg_start = 9'd{start[n]};" for i, n in enumerate(MESSAGES)]
    out += ["    default: xut_hw_msg_start = 9'd0;", "  endcase", "endfunction"]
    out += [
        "function [15:0] xut_hw_field_digits(input [3:0] f, input [15:0] nbits);",
        "  case (f)",
    ]
    for name, (tok, digits) in FIELDS.items():
        value = "nbits" if name == "bits" else f"16'd{digits}"
        out.append(f"    4'h{tok & 0xF:x}: xut_hw_field_digits = {value};")
    out += ["    default: xut_hw_field_digits = 16'd1;", "  endcase", "endfunction"]
    out += ["function [7:0] xut_hw_msg_rom(input [8:0] a);", "  case (a)"]
    out += [f"    9'd{a}: xut_hw_msg_rom = 8'h{b:02x};" for a, b in enumerate(data)]
    out += ["    default: xut_hw_msg_rom = 8'h00;", "  endcase", "endfunction"]
    return "\n".join(out) + "\n"
