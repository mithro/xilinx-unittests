// SPDX-License-Identifier: Apache-2.0
// vz_stale.v — the forced reg is read in the same block right after its assign and after
// its deassign, with no delay in between (ruling S18: the reads are substituted).
`timescale 1ps/1ps
module VZSTALE (output Q, output X, output Y, input C, input D, input S, input A);
  reg r, x, y;
  assign Q = r;
  assign X = x;
  assign Y = y;
  always @(S) begin
    if (S) begin
      assign r = A;
      x = r;
    end
    else begin
      deassign r;
      y = r;
    end
  end
  always @(posedge C) r <= D;
endmodule
