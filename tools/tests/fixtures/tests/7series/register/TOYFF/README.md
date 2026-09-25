# TOYFF (test fixture)

A toy D flip-flop used only by the xut tool tests; it is not a real primitive and has
no catalog entry (the tests build one by hand).

- `7series.TOYFF.L1.capture`: for `INIT` 0 and 1, D is captured on the rising edge of C
  (claim `TOYFF.C1`).
- `7series.TOYFF.L0.reject`: `INIT=1'bx` is illegal; the simulation must reject it
  (claim `TOYFF.R1`, `expect=reject`).
- `7series.TOYFF.L1.sv_basic`: a hand-written sv testbench (`sv/tb_toyff_basic.sv`, a
  toy DFF defined in the file) checks `Q` after GSR and one clock through
  `xut_trace.svh`.
