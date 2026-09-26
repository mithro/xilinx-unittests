// SPDX-License-Identifier: Apache-2.0
// GSR mid-simulation test shared by the flops unit (spec §4.3 sv style).
// The including file defines FLOP_TB, FLOP_PRIM and FLOP_CTRL.
// Checks only documented behaviour: GSR active -> INIT on Q (C4); capture after (C1).
// Clock edges while GSR is active are checkpoints only: UG953 does not describe them.
`timescale 1ps / 1ps
module `FLOP_TB;
`include "xut_trace.svh"
  reg C = 1'b0, CE = 1'b0, D = 1'b0, CTRL = 1'b0;
  wire Q0, Q1;
  `FLOP_PRIM #(.INIT(1'b0)) u0 (.Q(Q0), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));
  `FLOP_PRIM #(.INIT(1'b1)) u1 (.Q(Q1), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));

  task automatic cycle;
    begin
      #4000 C = 1'b1;
      #5000 C = 1'b0;
      #1000;
    end
  endtask

  task automatic phase(input integer n, input reg d);
    begin
      D = d;
      CE = 1'b1;
      cycle;                                   // both flops now hold d
      glbl.GSR_int = 1'b1;
      #1000;
      `XUT_CHECKN("gsr.Q0.P", n, Q0, 1'b0)
      `XUT_CHECKN("gsr.Q1.P", n, Q1, 1'b1)
      $fdisplay(xut_fd, "P%0d.gsr  Q0=%b Q1=%b", n, Q0, Q1);
      cycle;                                   // an edge while GSR is active
      $fdisplay(xut_fd, "P%0d.gsr_edge  Q0=%b Q1=%b", n, Q0, Q1);
      glbl.GSR_int = 1'b0;
      #1000;
      $fdisplay(xut_fd, "P%0d.released  Q0=%b Q1=%b", n, Q0, Q1);
      cycle;                                   // captures d again
      `XUT_CHECKN("after.Q0.P", n, Q0, d)
      `XUT_CHECKN("after.Q1.P", n, Q1, d)
      $fdisplay(xut_fd, "P%0d.after  Q0=%b Q1=%b", n, Q0, Q1);
    end
  endtask

  initial begin
    #120000;                                   // past glbl ROC_WIDTH (100 ns)
    `XUT_CHECK("P0.Q0", Q0, 1'b0)
    `XUT_CHECK("P0.Q1", Q1, 1'b1)
    `XUT_POINT2("P0", "Q0", Q0, "Q1", Q1)
    phase(1, 1'b1);
    phase(2, 1'b0);
    xut_finish;
  end
endmodule
