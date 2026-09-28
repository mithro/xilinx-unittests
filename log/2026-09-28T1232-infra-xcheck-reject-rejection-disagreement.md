# infra/xcheck-reject: crosscheck classifies a rejection disagreement (ruling S64)

## What changed

An L0 reject test whose golden model rejects the configuration while a UNISIM
simulator accepts it was recorded as a plain `fail`, but crosscheck never saw a
disagreement: both traces are header-only, so `_reject_agreement` counted the pair
as agreeing, the fail stayed unexplained (exit 4) and a listed `expected_divergence`
"matched no disagreement". A documented divergence could never reach exit 0.

`tools/xut/crosscheck.py`:

- `_reject_cfgs`: a reject configuration is one some traced result ran and no
  result has a sample of (every `expect=reject` trace is header-only, an accepting
  simulator's included). `_outcomes` reads its outcome from the config status
  (`pass` rejects, `fail` accepts; `xut.runners.reject`).
- `_rejection_diff`: the reject configurations two results both ran where one
  rejects and the other accepts. Classified like value disagreements:
  - golden vs every simulator that ran it: `doc-gap` (UG953 lists the legal values
    but promises no simulation-time check), merged into the rtl doc-gap finding;
  - simulator vs simulator: `sim-divergence` (every pair is compared, so the golden
    point is then skipped, as for values);
  - iverilog vs iverilog-vz: `transform-bug`, also in `companion_gap` (so a
    Verilator pass is not confirmed by a companion that splits from iverilog);
  - a flow vs RTL: `flow-mismatch`.
- It then goes through `_mark` like any finding: unlisted, exit 3; listed with an
  open finding, `known-divergence` (of the original class) with its points, exit 0;
  a closed or missing finding stays an issue (exit 4). Never masked.
- The iverilog-vz companion rule works unchanged: an iverilog-vz acceptance matching
  iverilog's is explained by iverilog's doc-gap.

`xut status generate` and PORTABILITY need no change: they list open findings from
`findings/*.md` and the per-runner result cells; the new disagreement is an ordinary
finding. The spec §8 text is unchanged (docs-owned); ruling S64 is described in the
crosscheck module docstring.

## Tests

- `tools/tests/test_crosscheck.py`, 11 new tests (toy fixtures): unlisted doc-gap exit
  3 (also through the CLI); listed with an open finding exit 0 and still reported;
  closed and missing finding exit 4; both reject still agree; simulator split is a
  sim-divergence; a 3-simulator split is one sim-divergence; a flow-mismatch; a value
  configuration is never a rejection disagreement; iverilog-vz accepting with iverilog
  is companion-explained (exit 0); iverilog-vz accepting what iverilog rejects is a
  transform-bug and not companion-explained. 9 of them fail on main's crosscheck.
- Full `tools/tests` suite (pytest -n 8 under `xut heavy`): 1991 passed, 8 skipped.
- Real case, luts worktree, this branch's xut, `xut crosscheck <PRIM> --model-source
  <ms>`: `L0.illegal_init` is `known-divergence` (of doc-gap) for all 8 primitives on
  both unisim-2025.2 and unisim-gh-2020.1 (main: incomplete, exit 4). LUT1-3 and
  CFGLUT5 exit 0 on both sources; LUT4, LUT5, LUT6, LUT6_2 exit 4, only from the
  separate Verilator `V3Gate.cpp:974` internal compile error.

## Next steps

- Review (code quality, correctness).
- `xut heavy` read `nice -n 19` as a `-n 19` parallelism (use `nice --adjustment=19`);
  worth a fix in `xut heavy`'s parallelism detection.
