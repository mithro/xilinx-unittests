// SPDX-License-Identifier: Apache-2.0
// vz_multi.v — multiple writers: two forcing blocks with different overrides.
`timescale 1ps/1ps
module VZMULTI (output Q, input C, input D, input A, input B);
  reg r;
  assign Q = r;
  always @(A)
    if (A) assign r = 1'b1;
    else deassign r;
  always @(B)
    if (B) assign r = D;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
