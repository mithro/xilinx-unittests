// SPDX-License-Identifier: Apache-2.0
// vz_bad_fork.v — refusal: a fork/join block in a block that forces a reg.
`timescale 1ps/1ps
module VZFORK (output Q, output Y, input C, input D, input S);
  reg r; reg y;
  assign Q = r; assign Y = y;
  always @(S) begin
    if (S) assign r = 1'b0; else deassign r;
    fork y = r; join
  end
  always @(posedge C) r <= D;
endmodule
