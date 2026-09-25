// SPDX-License-Identifier: Apache-2.0
// vz_bad_nestgen.v — refusal: a generate condition nested inside another.
`timescale 1ps/1ps
module VZNESTGEN (output Q, input C, input D, input S);
  parameter [0:0] P = 1'b1;
  parameter [0:0] Q_EN = 1'b1;
  reg r;
  assign Q = r;
  generate
    if (P) begin : g_p
      if (Q_EN) begin : g_q
        always @(S)
          if (S) assign r = 1'b0;
          else deassign r;
      end
    end
  endgenerate
  always @(posedge C) r <= D;
endmodule
