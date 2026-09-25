// SPDX-License-Identifier: Apache-2.0
// vz_bad_local.v — refusal: the override expression reads a block-local variable.
`timescale 1ps/1ps
module VZLOCAL (output Q, input C, input D, input S);
  reg r;
  assign Q = r;
  always @(S) begin : blk
    integer i;
    i = 1;
    if (S) assign r = i;
    else deassign r;
  end
  always @(posedge C) r <= D;
endmodule
