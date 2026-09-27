// SPDX-License-Identifier: Apache-2.0
// X-input test shared by the luts unit (LUT1-LUT6, LUT6_2; spec §4.3 sv style).
// The including file defines LUT_TB (the module name), LUT_N (the input count) and
// LUT_INST (one instance of the primitive on I[LUT_N-1:0] and O; LUT6_2 puts O6 on O and
// O5 on O5, and also defines LUT_DUAL). INIT is a module parameter (test.yaml configs).
// Checked (documented, the logic table): every defined address reads INIT[address]
// (claim C1; for LUT6_2 also O5 = INIT[address mod 32], claim C2).
// Checkpoints only (UG953 does not define x behaviour): for each input k, x on I[k] where
// the two INIT bits it selects agree (X<k>.same) and where they differ (X<k>.diff), then
// x on every input (Xall). xut crosscheck compares them between simulators.
`timescale 1ps / 1ps
module `LUT_TB #(
    parameter [(1 << `LUT_N) - 1:0] INIT = {(1 << `LUT_N){1'b0}}
);
`include "xut_trace.svh"
  // No declaration initialiser: a combinational UNISIM model can miss one at time 0.
  // The inputs get their first value by a time-0 non-blocking update instead, as in the
  // vector testbench, after every model process is waiting.
  reg [`LUT_N-1:0] I;
  wire O;
`ifdef LUT_DUAL
  wire O5;
`endif
  `LUT_INST

  integer a, k;
  reg same_done, diff_done;

  task automatic point(input integer kk, input reg same);
    begin
      xut_open;
`ifdef LUT_DUAL
      if (same) $fdisplay(xut_fd, "X%0d.same  O6=%b O5=%b", kk, O, O5);
      else $fdisplay(xut_fd, "X%0d.diff  O6=%b O5=%b", kk, O, O5);
`else
      if (same) $fdisplay(xut_fd, "X%0d.same  O=%b", kk, O);
      else $fdisplay(xut_fd, "X%0d.diff  O=%b", kk, O);
`endif
    end
  endtask

  initial begin
    I <= {`LUT_N{1'b0}};
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("O.a", a, O, INIT[a])
`ifdef LUT_DUAL
      `XUT_CHECKN("O5.a", a, O5, INIT[a%32])
`endif
    end
    for (k = 0; k < `LUT_N; k = k + 1) begin
      same_done = 1'b0;
      diff_done = 1'b0;
      for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
        if (((a >> k) & 1) == 0 && !same_done && INIT[a] == INIT[a|(1<<k)]) begin
          same_done = 1'b1;
          I = a;
          I[k] = 1'bx;
          #1000;
          point(k, 1'b1);
        end
        if (((a >> k) & 1) == 0 && !diff_done && INIT[a] != INIT[a|(1<<k)]) begin
          diff_done = 1'b1;
          I = a;
          I[k] = 1'bx;
          #1000;
          point(k, 1'b0);
        end
      end
    end
    I = {`LUT_N{1'bx}};
    #1000;
    xut_open;
`ifdef LUT_DUAL
    $fdisplay(xut_fd, "Xall  O6=%b O5=%b", O, O5);
`else
    $fdisplay(xut_fd, "Xall  O=%b", O);
`endif
    xut_finish;
  end
endmodule
