// SPDX-License-Identifier: Apache-2.0
// vz_generate.v — the forced reg is written in both arms of a generate if.
`timescale 1ps/1ps
module VZGEN (output Q, input C, input D, input R);
  parameter [0:0] IS_C_INVERTED = 1'b0;
  reg r;
  assign Q = r;
  always @(R)
    if (R) assign r = 1'b0;
    else deassign r;
  generate
    if (IS_C_INVERTED) begin : g_neg
      always @(negedge C) r <= D;
    end else begin : g_pos
      always @(posedge C) r <= D;
    end
  endgenerate
endmodule
