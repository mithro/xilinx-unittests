// SPDX-License-Identifier: Apache-2.0
// vz_bad_wrap.v — refusal: a read at the top of an `always` loop sees the override state
// left by the previous iteration (none on the first), so it cannot be substituted.
`timescale 1ps/1ps
module VZWRAP (output Q, output Y, input C, input D, input S);
  reg r; reg y;
  assign Q = r; assign Y = y;
  always begin
    y = r;
    @(S);
    if (S) assign r = 1'b0; else deassign r;
  end
  always @(posedge C) r <= D;
endmodule
