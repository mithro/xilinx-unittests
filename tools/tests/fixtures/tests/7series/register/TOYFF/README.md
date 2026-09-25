# TOYFF (test fixture)

A toy D flip-flop used only by the xut tool tests; it is not a real primitive and has
no catalog entry (the tests build one by hand).

- `7series.TOYFF.L1.capture`: for `INIT` 0 and 1, D is captured on the rising edge of C
  (claim `TOYFF.C1`).
