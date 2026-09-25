// SPDX-License-Identifier: Apache-2.0
// vz_bad_select.v — refusal: a procedural assign to a bit-select.
`timescale 1ps/1ps
module VZBADSEL (output [1:0] Q, input C, input [1:0] D, input S);
  reg [1:0] q;
  assign Q = q;
  always @(S)
    if (S) assign q[0] = 1'b1;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
