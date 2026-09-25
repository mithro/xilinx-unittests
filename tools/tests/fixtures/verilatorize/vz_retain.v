// SPDX-License-Identifier: Apache-2.0
// vz_retain.v — deassign value retention: nothing else writes q, so it keeps
// the forced value after the deassign.
`timescale 1ps/1ps
module VZRETAIN (output Q, input S);
  reg q;
  assign Q = q;
  initial q = 1'b0;
  always @(S)
    if (S) assign q = 1'b1;
    else deassign q;
endmodule
