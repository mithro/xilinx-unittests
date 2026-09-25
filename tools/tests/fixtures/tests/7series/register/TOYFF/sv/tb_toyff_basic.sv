// SPDX-License-Identifier: Apache-2.0
// TOYFF sv fixture (xut tool tests only): a toy D flip-flop defined in this file, with
// a glbl.GSR preset like UNISIM's, checked through xut_trace.svh (spec §4.3).
`timescale 1ps / 1ps
module toyff_sv_dff (output wire Q, input wire C, input wire D);
  reg q;
  always @(posedge C or posedge glbl.GSR)
    if (glbl.GSR) q <= 1'b1;
    else q <= D;
  assign Q = q;
endmodule

module tb_toyff_basic;
`include "xut_trace.svh"
  reg c = 1'b0, d = 1'b0;
  wire q;
  toyff_sv_dff dut (.Q(q), .C(c), .D(d));
  initial begin
    #120000;  // past glbl's start-up GSR pulse (ROC_WIDTH, 100 ns): preset to 1
    `XUT_CHECK("gsr", q, 1'b1)
    `XUT_POINT1("after_gsr", "Q", q)
    #1000 c = 1'b1;  // D=0 is captured
    #1000 c = 1'b0;
    `XUT_CHECK("clk", q, 1'b0)
    `XUT_POINT1("after_clk", "Q", q)
    glbl.GSR_int = 1'b1;  // the testbench drives glbl too: a GSR pulse presets again
    #1000 glbl.GSR_int = 1'b0;
    #1000;
    `XUT_CHECK("gsr_pulse", q, 1'b1)
    xut_finish;
  end
endmodule
