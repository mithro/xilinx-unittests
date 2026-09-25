// SPDX-License-Identifier: Apache-2.0
// vz_bad_rao.v — refusal: the forced reg is read after its assign in the same block.
`timescale 1ps/1ps
module VZRAO (output Q, output X, input C, input D, input S);
  reg r, x;
  assign Q = r;
  assign X = x;
  always @(S) begin
    assign r = 1'b0;
    x = r;
  end
  always @(posedge C) r <= D;
endmodule
