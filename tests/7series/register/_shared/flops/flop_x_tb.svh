// SPDX-License-Identifier: Apache-2.0
// X-input test shared by the flops unit. The including file defines FLOP_TB,
// FLOP_PRIM, FLOP_CTRL, FLOP_FORCED (1'b0 or 1'b1) and FLOP_ASYNC (0 or 1).
// Checked (documented): CE Low holds Q with D = x (C2); an active control forces Q
// with D = x and CE = x (C3). Checkpoints only (undocumented): x on D with CE High,
// x on CE, x on the control.
`timescale 1ps / 1ps
module `FLOP_TB;
`include "xut_trace.svh"
  reg C = 1'b0, CE = 1'b0, D = 1'b0, CTRL = 1'b0;
  wire Q;
  `FLOP_PRIM u (.Q(Q), .C(C), .CE(CE), .D(D), .`FLOP_CTRL(CTRL));

  task automatic cycle;
    begin
      #4000 C = 1'b1;
      #5000 C = 1'b0;
      #1000;
    end
  endtask

  task automatic load(input reg v);
    begin
      CTRL = 1'b0;
      #1000;
      D = v;
      CE = 1'b1;
      cycle;
    end
  endtask

  initial begin
    #120000;
    load(~`FLOP_FORCED);                      // X1: CE Low, D = x -> hold (C2)
    CE = 1'b0;
    D = 1'bx;
    cycle;
    cycle;
    `XUT_CHECK("X1", Q, ~`FLOP_FORCED)
    `XUT_POINT1("X1", "Q", Q)
    load(~`FLOP_FORCED);                      // X2: control active, D = CE = x (C3)
    D = 1'bx;
    CE = 1'bx;
    #1000 CTRL = 1'b1;
    #1000;
    if (`FLOP_ASYNC) begin
      `XUT_CHECK("X2a", Q, `FLOP_FORCED)
    end
    `XUT_POINT1("X2a", "Q", Q)
    cycle;
    `XUT_CHECK("X2", Q, `FLOP_FORCED)
    `XUT_POINT1("X2", "Q", Q)
    load(~`FLOP_FORCED);                      // X3: CE High, D = x (undocumented)
    D = 1'bx;
    cycle;
    `XUT_POINT1("X3", "Q", Q)
    load(1'b0);                               // X4: CE = x, D != Q (undocumented)
    D = 1'b1;
    CE = 1'bx;
    cycle;
    `XUT_POINT1("X4", "Q", Q)
    load(~`FLOP_FORCED);                      // X5: control = x (undocumented)
    #1000 CTRL = 1'bx;
    #1000;
    `XUT_POINT1("X5a", "Q", Q)
    cycle;
    `XUT_POINT1("X5", "Q", Q)
    CTRL = 1'b0;
    xut_finish;
  end
endmodule
