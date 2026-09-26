# SPDX-License-Identifier: Apache-2.0

# infra/xvec-strings: .xvec writer escapes quoted string values (S34.3)

## What changed

Ruling S34.3 (`.superpowers/sdd/2026-09-25-step2-core-infra-pilot/progress.md`,
via the `infra/sim-formats` worktree) reverses decision "I1" narrowly: the
`.xvec` writer no longer refuses a header value containing a literal `"`. It
now escapes `"` and `\` exactly as the parser (`_unquote`) already accepts
them, so a string attribute such as `IOSTANDARD="LVCMOS33"` round-trips
through `attr.IOSTANDARD` instead of raising. This unblocks the bufg/io work
units (spec §5.1/§5.3), whose catalog attributes include Verilog string
literals.

`tools/xut/formats/xvec.py`:

- `_escape_quoted`: previously refused any `"` in the value. Now escapes a
  backslash first (`\` → `\\`), then a literal quote (`"` → `\"`) — the exact
  inverse of the order `_unquote` undoes them in (backslash-doubling first
  avoids ambiguity at a quote boundary that was produced by the escaping
  itself; verified by fuzzing 200k random strings drawn from an alphabet of
  `a b \ " # =` through `escape`/`unescape` before touching the source, 0
  mismatches).
- New `_check_representable` factors out the still-refused case: any C0
  control character (`0x00`-`0x1f`) or DEL (`0x7f`), newline and CR included.
  It is called both from `_quote` (so a *bare*, unquoted token — e.g. a
  `\x00` that doesn't trip the whitespace/quote/hash-triggered quoting — is
  still checked) and from `_escape_quoted` (covers `hw_renderable`'s
  `reason="..."`, which is always quoted). Before this change a bare-token
  control character such as `\x00`, `\x07` or `\x7f` silently passed through
  unchecked, since the quoting trigger regex (`[\s"#]`) only quotes on
  whitespace/quote/hash and `_escape_quoted` was only ever reached through
  that path — an existing gap this change also closes, not one S34.3 asked
  for but a direct consequence of centralising the check.
- `_quote`'s bare-vs-quoted trigger regex is unchanged (whitespace, `"`, `#`):
  a bare backslash alone still round-trips as a literal, unescaped bare
  token, since bare tokens are never unescaped by the parser.

**Parser unchanged.** `_unquote` (backslash-quote pairs, then doubled
backslashes) already accepted exactly what the new escaper produces; no
parser bug surfaced. `_KV`'s quoted-token grammar
(`"(?:[^"\\]|\\.)*"`) already allowed an escaped quote or backslash inside a
quoted header value.

## Spec and AGENTS.md

- `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md`
  §5.3 gets a new bullet stating the escaping rule and naming
  `IOSTANDARD="LVCMOS33"` as the motivating case (ruling S34.3).
- `AGENTS.md` does not mention the writer's quote restriction anywhere
  (checked by grep); nothing to update there.

## Tests (TDD)

Added to `tools/tests/test_xvec.py` (written first, confirmed red against
the unmodified writer, then green):

- `test_hw_reason_with_quote_round_trips` replaces
  `test_dumps_raises_on_unrepresentable_quote_in_hw_reason` (I1's refusal is
  reversed, not merely narrowed, for `hw_reason`).
- `test_dumps_raises_on_other_control_chars_in_header_value` /
  `test_dumps_raises_on_control_char_in_hw_reason`: parametrized over `\r`,
  `\x00`, `\x07`, `\x1f`, `\x7f` — the writer still refuses every character
  the parser cannot represent, with a clear "cannot be represented" error.
  `test_dumps_raises_on_unrepresentable_newline_in_header_value` (existing)
  is kept as-is.
- `test_attr_value_round_trips`: parametrized over spaces, `"`, `\`, `=`,
  `#`, a trailing backslash, an empty string, the literal
  `"LVCMOS33"` Verilog string literal, a value mixing all of the above, and
  two escaping-order traps (`\"` and `""`, `\\`) — for every value,
  `loads(dumps(v)) == v` and `v.attrs == {"NOTE": value}`.
- `test_attr_value_iostandard_round_trips`: the concrete
  `attr.IOSTANDARD="LVCMOS33"` case named in S34.3.
- `test_attr_value_as_rendered_by_wrap_render_attr_round_trips`: builds the
  value with `xut.wrap.render_attr({"kind": "string", ...}, "LVCMOS33")` —
  the exact function `spec_from_catalog`/`_render_attrs` uses — confirming
  the literal that actually flows from the wrapper into
  `VecBuilder.build`'s `attr.<NAME>` header keys (`tools/xut/stimgen.py:299`)
  round-trips unchanged.

## Test results

- `uv run pytest -q tools/tests/test_xvec.py`: 118 passed.
- `uv run pytest -q -n 16 -m "not slow" tools/tests`: 1299 passed, 1 skipped.
- `uv run ruff format tools/`: 78 files left unchanged (no reformatting
  needed beyond the edits already made).
- `uv run ruff check tools/`: all checks passed, 0 issues.
- `uv run xut lint --branch`: 0 errors, 0 warnings.

Logs under
`/tmp/claude-1000/-home-tim-github-f4pga-xilinx-unittests/ea2a4341-5abd-4046-9b32-e90287ec016d/scratchpad/xvs/`
(`uv-sync.log`, `pytest-red.log`, `pytest-green.log`, `pytest-green2.log`,
`pytest-fast.log`, `ruff-format.log`, `ruff-check.log`,
`lint-branch-pre.log`).

## Next steps

- None outstanding for this follow-up. The bufg/io units (S27 step 3) can now
  record `IOSTANDARD` and other string attributes in their `.xvec` headers.
- Task 14's equivalence-check stimulus header still omits attributes
  entirely (a separate workaround on another branch, per the brief); this
  branch does not touch that code.
