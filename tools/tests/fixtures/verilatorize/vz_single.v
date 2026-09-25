// SPDX-License-Identifier: Apache-2.0
// vz_single.v — single writer: one forcing block, one ordinary writer.
`timescale 1ps/1ps
module VZSINGLE (output Q, input C, input D, input CLR);
  reg q;
  assign Q = q;
  always @(CLR)
    if (CLR) assign q = 1'b0;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
