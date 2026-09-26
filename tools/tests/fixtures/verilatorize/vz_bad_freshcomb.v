// SPDX-License-Identifier: Apache-2.0
// vz_bad_freshcomb.v — MMCME2_ADV-style: a forced real is written and then read in an `@*`
// block. Refused: Verilator evaluates the block as combinational logic, so it would re-run
// it when the override is released even though X does not change.
`timescale 1ps/1ps
module VZFRESHCOMB (output [31:0] N, input [7:0] P, input EN, input S);
  real rl;
  integer n;
  assign N = n;
  always @(*) begin
    if (EN) begin
      rl = P * 1.5;
      n = $rtoi(rl);
    end
  end
  always @(S)
    if (S) assign rl = 50.0;
    else deassign rl;
endmodule
