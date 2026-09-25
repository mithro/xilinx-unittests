// SPDX-License-Identifier: Apache-2.0
// vz_nonconst.v — a non-constant override expression, evaluated continuously.
`timescale 1ps/1ps
module VZNONCONST (output Q, input C, input D, input S, input A, input B);
  reg r;
  assign Q = r;
  always @(S)
    if (S) assign r = A & B;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
