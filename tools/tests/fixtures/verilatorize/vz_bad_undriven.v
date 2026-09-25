// SPDX-License-Identifier: Apache-2.0
// vz_bad_undriven.v — refusal: a signal in the trigger cone has no driver at all.
`timescale 1ps/1ps
module VZUNDRIVEN (output Q, input C, input D);
  wire en;
  reg r;
  assign Q = r;
  always @(en)
    if (en) assign r = 1'b0;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
