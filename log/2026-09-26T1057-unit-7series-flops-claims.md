# flops: catalog overrides and behavioural claims (Task 19)

Branch `unit/7series/flops`, stacked on `infra/crosscheck` (3c97552).

## What changed

- Added `catalog/7series/{FDRE,FDSE,FDCE,FDPE}.overrides.yaml`. Each one has claims
  `<PRIM>.C1`..`C8`, paraphrased from UG953 v2026.1 with `doc:<page>` provenance:
  - C1-C4 from the Introduction and Logic Table: FDCE p369, FDPE p372, FDRE p375, FDSE p378.
  - C5-C8 from the Programmable Inversion and attribute table: FDCE p370, FDPE p373,
    FDRE p376, FDSE p379.
- `FDCE.CLR` and `FDPE.PRE` (class `async`) are declared `active: high`. The source is
  UG953 p370/p373: IS_<pin>_INVERTED=1 turns a non-clock pin from active-High into
  active-Low. The logic tables agree. This gives `port:<P>:assert`/`:release` bins (ruling
  S19). `FDRE.R` and `FDSE.S` keep the generated class `data`: they are synchronous, so
  they get the `:0`/`:1` bins.
- I did not add attribute overrides. The plan's brief added `allowed: [1'b0, 1'b1]` for the
  IS_*_INVERTED attributes, but the generated catalog already has exactly that list, so the
  overrides would change nothing.
- I did not declare crosses. UG953 does not document any interaction between two of these
  attributes, INIT × IS_C_INVERTED included.
- Bins per primitive: 28, which is 12 port bins + 8 attribute-value bins + 8 claims. The
  plan's figure of 21 is superseded by ruling S19.

## Tests

- `xut lint` passes with 0 issues. `xut lint --branch --base infra/crosscheck` also passes
  with 0 issues.
- Fast suite (`-m "not slow" -n 8`): 1273 passed, 2 failed. Both failing tests are in the
  infra-owned `tools/tests/test_status_schema.py` and check the live checkout:
  - `test_fdre_bins_are_the_ruling_s19_set` hard-codes the 20 bins FDRE had with no claims.
    Its docstring already says the count becomes 28 once the pilot adds its claims.
  - `test_every_status_stub_matches_its_catalog_entry_and_work_unit`: the committed
    never-recorded FD* stubs no longer match `coverage_bins`, because they lack the claim
    bins and the new port-class bins. Only `xut status init --refresh-bins` fixes them, and
    only on main (ruling S20).

## Next steps / TODO (infra dependency, AGENTS.md §13)

- An infra follow-up has to relax or update these two invariant tests for primitives whose
  unit has added overrides. The alternative is for the orchestrator to authorise refreshing
  the four FD* stubs on this branch. The unit branch may not edit `tools/tests/**`.
- Task 20: golden model.
