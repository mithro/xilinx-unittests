// SPDX-License-Identifier: Apache-2.0
// vz_bad_genparam.v — refusal: a generate condition over integer parameters with no
// literal to derive candidate values from.
`timescale 1ps/1ps
module VZBADGEN (output Q, input C, input D, input S);
  parameter integer WIDTH = 4;
  parameter integer DEPTH = 8;
  reg r;
  assign Q = r;
  always @(S)
    if (S) assign r = 1'b0;
    else deassign r;
  generate
    if (WIDTH > DEPTH) begin : g_wide
      always @(posedge C) r <= D;
    end else begin : g_deep
      always @(negedge C) r <= D;
    end
  endgenerate
endmodule
