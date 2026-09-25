// SPDX-License-Identifier: Apache-2.0
// vz_bad_ansi.v — refusal: the forced reg is an ANSI output reg.
`timescale 1ps/1ps
module VZANSI (output reg Q, input S);
  always @(S)
    if (S) assign Q = 1'b0;
    else deassign Q;
endmodule
