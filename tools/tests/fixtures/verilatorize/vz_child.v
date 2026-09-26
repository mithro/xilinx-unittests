// SPDX-License-Identifier: Apache-2.0
// vz_child.v — CE defaults to enabled when unconnected (a z-compare, ruling S38).
`timescale 1ps/1ps
module VZCHILD #(parameter [0:0] INIT = 1'b0) (output Q, input C, input CE, input D);
  reg q = INIT;
  always @(posedge C) if (CE || (CE === 1'bz)) q <= D;
  assign Q = q;
endmodule
