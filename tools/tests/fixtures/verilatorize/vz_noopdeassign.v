// SPDX-License-Identifier: Apache-2.0
// vz_noopdeassign.v — a reg that is deassigned but never assigned (FF18_INTERNAL_VLOG
// ALMOSTFULL): the deassign is a no-op in Verilog, so the reg is not transformed.
`timescale 1ps/1ps
module VZNOOP (output Q, input C, input D, input RST);
  reg q;
  assign Q = q;
  always @(RST)
    if (RST) q = 1'b0;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
