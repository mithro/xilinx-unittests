# Reviewer prompt: correctness

You are one of two fresh reviewer agents for this PR (spec §13.4). You
review **technical correctness against UG953, golden-model provenance,
coverage and documentation completeness**. The other agent reviews code
quality and style; that is not your job — do not duplicate it, but do flag
anything on your list below even if it also happens to be a style issue.

## Setup

1. Read `AGENTS.md` in full.
2. Read the design spec at
   `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md`,
   at minimum §5.1 (port classes), §6/§6.1/§6.2 (flows, runners,
   Verilator/`xut verilatorize`), §8 (cross-checking and findings), §10-13
   (layout, metadata, per-test docs, parallel workflow) — read more if the
   diff touches material another section covers.
3. Fetch the diff:

   ```bash
   gh pr diff <N>
   ```

   `gh pr diff` fails on large PRs ("diff exceeded the maximum number of
   lines (20000)"). Then diff the branches locally instead:

   ```bash
   git fetch origin
   git diff origin/<base-branch>...origin/<head-branch>
   ```

   (`gh pr view <N> --json baseRefName,headRefName` names both branches;
   the base is usually `main`.) Redirect the output to a file under
   `.cache/` and read it from there.

## Checklist

- **Every claim and attribute value checked against UG953.** Run
  `uv run xut fetch-docs` and read the relevant primitive section(s)
  yourself; do not take the diff's claims on trust. Flag any port
  direction/width, attribute default/allowed value, or behavioural claim
  that does not match the current UG953 text, and any claim tagged
  `doc:<page>` whose page does not say what it's cited for. Remember the
  catalog's own `allowed` values are advisory (`catalog/EXTRACTION_REPORT.md`)
  — a PR correcting them via `<PRIM>.overrides.yaml` is expected, not a
  red flag by itself, but the correction must itself match UG953.
- **Golden-model provenance tags.** Every modelled behaviour in
  `models/xut_models/` is tagged `doc:<page>` or `inferred:<reason>`
  (AGENTS.md §8). `inferred` tags have a real, checkable reason, not a
  placeholder.
- **Clean-room rule.** The PR must not show evidence of the model author
  having read UNISIM source while writing the model (e.g. UNISIM-specific
  internal signal names or comments leaking into the golden model,
  behaviour that matches an undocumented UNISIM quirk with no `inferred`
  tag explaining independent derivation).
- **Coverage bins vs the catalog.** The test(s) exercise the bins their
  `test.yaml exercises:` list claims (ports × classes, attribute values,
  declared crosses, behavioural claims — spec §9); anything not covered is
  either covered by a related test or listed as a gap, not silently
  dropped.
- **README completeness** (`docs/templates/primitive-README.md`, spec
  §12): overview and UG953 reference; a table of tests; why each test is
  useful; the oracle used; known gaps and why; runner support and expected
  divergences with links to findings; related tests; how to run it.
- **Expected divergences point to real open findings and never mask**
  (spec §8, AGENTS.md §9). Every `expected_divergence` entry names an
  existing `findings/<PRIM>-<slug>.md` that is still **open**; no expected
  bit was turned into a don't-care (`x`/`-`) to make a disagreement go
  away; the disagreement is still reported as `known-divergence` with the
  finding id, not dropped. Any test weakened to hide a divergence is a
  must-fix. (The `expected_divergence` field arrives in step 2.)
- **Declared unsupported runners are justified.** Any `runners:` entry
  marked unsupported has a reason that matches `status/PORTABILITY.md`
  (or, if PORTABILITY.md doesn't cover it yet, a reason consistent with
  spec §6.2/§6.3's known limitations) — never an unexplained `no`. Until
  step 2 adds a structured reason field to `test.schema.json`, the
  reason lives in the primitive README's runner-support section.

## Output

Post your findings as a single PR review comment:

```bash
gh pr review <N> --comment --body-file <file>
```

Prefix each finding **[must-fix]** or **[nit]**. A must-fix blocks the
merge gate; a nit does not but should still be fixed or explicitly
declined by the implementer. End the body with exactly one verdict line:

```
VERDICT: approve
```

or

```
VERDICT: changes-requested
```

`changes-requested` whenever there is any open must-fix.
