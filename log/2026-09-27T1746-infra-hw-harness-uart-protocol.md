# infra/hw-harness — Task 1: harness UART protocol and message ROM

## What changed

- Created `tools/xut/hw/__init__.py` (package docstring, spec §7).
- Created `tools/xut/hw/proto.py`: the stepped harness's UART protocol, standard-library
  only. Implements `PROTO`, `CMD_ID`/`CMD_LOAD`/`CMD_RUN`, `STATUS`/`STATUS_CODE`,
  `FIELDS`, `MESSAGES`, `render`/`parse`, the frozen dataclasses `IdReply`/`LoadReply`/
  `RunReply`, `load_frame`/`parse_id`/`parse_load`/`parse_run`, `rom`/`render_rom_vh`,
  and `ProtoError`.
- Added the `xut hw` CLI group with `gen-rtl`, which regenerates
  `tools/xut/hdl/hw/xut_hw_msgs.vh` (message numbers, field tokens, field widths and the
  223-byte message ROM as Verilog localparams/functions) from `xut.hw.proto.MESSAGES`.
- Added `tools/tests/test_hw_proto.py` per the task brief, TDD-first (confirmed the
  `ModuleNotFoundError: No module named 'xut.hw'` collection failure before
  implementing).

## Test results

- `uv run pytest tools/tests/test_hw_proto.py -v -n 4` (scoped per ruling S53): all 17
  tests pass, including the round-trip of every message template, `load_frame` framing
  and CRC, `parse_run`'s CRC/truncation/reordering/err-line checks, the ROM
  reconstruction test, and the "committed ROM is current" pin against
  `render_rom_vh()`.
- `uv run ruff format` / `uv run ruff check` on the touched files: clean, no changes.
- `uv run xut lint --branch`: 0 errors, 1 pre-existing warning (`status/PORTABILITY.md`
  not generated yet — orchestrator-only, unrelated to this branch).

## Next steps

- Task 2 onward (image compiler, reference interpreter, harness RTL, simulation) builds
  on this protocol module.
