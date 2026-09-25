// SPDX-License-Identifier: Apache-2.0
// vz_delay.v — a non-blocking write with an intra-assignment delay.
`timescale 1ps/1ps
module VZDELAY (output Q, input C, input D, input R);
  reg q;
  assign Q = q;
  always @(R)
    if (R) assign q = 1'b0;
    else deassign q;
  always @(posedge C) q <= #100 D;
endmodule
