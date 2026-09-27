# Task 2 fix round 1: address `task-2-review.md`

## What changed

- `tools/tests/test_hw_image.py`: added `test_opcode_literal_values_match_the_brief`
  (pins `OP_SET=0x1, OP_COMMIT=0x2, OP_EDGE=0x3, OP_WAIT=0x4, OP_SAMPLE=0x5,
  OP_END=0xF`, `CHUNK=16`, `MAX_CHUNKS=4096`, `MAX_CLOCKS=4096`, `MAX_WAIT=2**28-1`,
  `MAXWORDS=8192`, `MARGIN=16` as literal ints, not via a `decode(w_x(...))` round
  trip) and `test_golden_image_is_exact_ints_from_the_brief` (one small program's
  encoded words asserted against literal hex ints computed by hand from the
  brief's bit layout — op in `[31:28]`; SET `[27:16]` chunk, `[15:0]` data; EDGE
  `[12]` level, `[11:0]` clock — rather than by calling `w_set`/`w_edge`/`decode`).
  Addresses the review's Important finding: a swapped opcode value would previously
  have passed every existing test, since encode and decode both consult the same
  module constants.
- `tools/tests/test_hw_compile.py`: added one `compile_program` refusal test per
  remaining `validate` `hw_reasons` category not yet covered (x/z, glbl GSR and
  `expect=reject` already had tests): `test_pad_class_is_unrenderable` (a pad-class
  bit), `test_free_running_clock_is_unrenderable` (a `mode=free` clock, built
  directly via `xut.formats.xvec.loads` since `VecBuilder` always emits stepped
  clocks), `test_simultaneous_group_is_unrenderable` (via `VecBuilder.simultaneous()`)
  and `test_event_gap_is_unrenderable` (two sets 400 ps apart, below the 1000 ps
  minimum, also built via `loads`). Each asserts the validator's own reason text
  reaches `HwUnrenderable` (`match=`). Addresses the review's Minor finding.

One iteration needed on `test_free_running_clock_is_unrenderable`: the first
attempt placed its lone `sample` at a time that happened to coincide with a
computed free-clock edge, which `validate`'s structural check ("a sample shares
its time with a change") refuses before `hw_reasons` is even consulted — moved
the sample to a time with no input change at all (the same clock parameters as
`test_validate.py`'s own known-good case), which now exercises the intended
`FREE_CLOCK_REASON` path.

Also corrected `task-2-report.md`'s test-count breakdown (review's Minor finding
1): it said "8 new... 47 pre-existing"; the actual pre-fix-round-1 split (per
`pytest --collect-only`) was 14 new (9 + 5) + 41 pre-existing = 55. The grand
total and pass/fail outcome were always right; only the breakdown was wrong.

## Test results

`uv run pytest tools/tests/test_hw_image.py tools/tests/test_hw_compile.py
tools/tests/test_stimcompile.py -v -n 4`, scoped (`systemd-run ... -p
MemoryMax=8G -p MemorySwapMax=0`): **61 passed**, 0 failed, 0 skipped — 20 new
(11 in `test_hw_image.py` incl. the 4 parametrized `test_builder_refuses` cases,
9 in `test_hw_compile.py`) + 41 pre-existing `test_stimcompile.py` tests,
confirmed unaffected. `pytest --collect-only` on the two new files independently
confirms the 20 count.

`ruff format tools`: 105 files left unchanged (one intermediate run reformatted a
line-wrap in `test_hw_compile.py`; the reformatted version was kept, as the
Global Constraints direct). `ruff check tools`: all checks passed.

## Next steps

Task 3 (the reference interpreter and harness RTL) can now rely on the opcode
table being pinned by a literal-value test, not just a self-consistent round
trip, and on `compile_program`'s refusal path being exercised across every
`hw_reasons` category the validator can currently raise.
