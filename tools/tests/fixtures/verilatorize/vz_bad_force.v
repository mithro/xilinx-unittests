// SPDX-License-Identifier: Apache-2.0
// vz_bad_force.v — refusal: force/release.
`timescale 1ps/1ps
module VZFORCE (output Q, input C, input D, input S);
  reg q;
  assign Q = q;
  always @(S)
    if (S) force q = 1'b0;
    else release q;
  always @(posedge C) q <= D;
endmodule
