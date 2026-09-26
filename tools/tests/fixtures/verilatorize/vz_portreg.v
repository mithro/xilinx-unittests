// SPDX-License-Identifier: Apache-2.0
// vz_portreg.v — the forced reg is a non-ANSI `output reg` port (FF18_INTERNAL_VLOG-style).
`timescale 1ps/1ps
module VZPORTREG (Q, C, D, S);
  output reg [1:0] Q;
  input C, D, S;
  always @(S)
    if (S) assign Q = 2'b00;
    else deassign Q;
  always @(posedge C) Q <= {Q[0], D};
endmodule
