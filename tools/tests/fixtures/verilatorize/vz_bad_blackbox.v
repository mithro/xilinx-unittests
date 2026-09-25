// SPDX-License-Identifier: Apache-2.0
// vz_bad_blackbox.v — refusal: the trigger cone reaches an unknown module's output.
`timescale 1ps/1ps
module VZBLACKBOX (output Q, input C, input D, input S);
  wire en;
  reg r;
  SOMETHING_UNKNOWN u (.o(en), .i(S));
  assign Q = r;
  always @(en)
    if (en) assign r = 1'b0;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
