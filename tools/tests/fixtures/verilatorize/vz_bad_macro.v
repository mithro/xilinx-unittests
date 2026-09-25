// SPDX-License-Identifier: Apache-2.0
// vz_bad_macro.v — refusal: the procedural assign comes from a macro expansion.
`timescale 1ps/1ps
`define FORCE_R assign r = 1'b0
module VZMACRO (output Q, input C, input D, input S);
  reg r;
  assign Q = r;
  always @(S)
    if (S) `FORCE_R;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
