// SPDX-License-Identifier: Apache-2.0
// Toy D flip-flop for the harness tests (tools/tests only; not a UNISIM model):
// Q powers up as INIT and takes D 100 ps after a rising C.
`timescale 1ps / 1ps
module TOYFF #(parameter [0:0] INIT = 1'b0) (output reg Q, input wire C, input wire D);
  initial Q = INIT;
  always @(posedge C) Q <= #100 D;
endmodule
