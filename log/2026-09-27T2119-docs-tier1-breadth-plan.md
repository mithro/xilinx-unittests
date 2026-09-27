# docs/tier1-breadth: breadth-first coverage (ruling S58)

## What changed
- Owner directive (2026-09-28): get initial, basic, wide coverage of the important,
  commonly used primitives first, then return for full coverage of rarely used features.
- The playbook gains Appendix T, which defines:
  - the Tier 1 deliverable per primitive: core claims, a model of core behaviour, L0 smoke,
    and one L1 test per core claim with its S55 mutant, on every simulator the portability
    table allows. Everything else is listed as `tier-2:` gaps.
  - the Tier 1 order by how commonly each unit is used: luts, carry, muxf, srl, lutram, bram,
    dsp, basic io buffers, bufg, mmcm_pll, ddr_regs, latches, rom, bram_fifo, delay, then the rest.
  - that P2 (`smoke_attrs`) and P3 (clock observers) are pulled forward.
- Tier 1 never weakens a check or marks a unit complete.

## Tests
- Docs only. `xut lint --branch` passes.

## Next steps
- Two reviewers, then merge.
- Schedule P2 and P3 on infra branches alongside carry, muxf, srl and lutram.

## Correctness review fix
- Must-fix: every documented claim stays in `claims`, so the Tier 2 debt shows as uncovered
  bins. Every deferral is a leading-bin gap (`claim:X.C7 — tier-2: …`), which lint
  `bins-accounted` accounts for.
- Nits:
  - reject tests are Tier 1;
  - a legal value the model does not model yet is not an illegal value;
  - a skipped GSR test's bins get `tier-2:` gaps;
  - "Tier 1" goes in the README header, not in status notes (AGENTS.md §7);
  - the P2 wording now matches Appendix W and D11;
  - Appendix W's order sentence defers to Appendix T.
