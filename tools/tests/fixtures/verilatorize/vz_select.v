// SPDX-License-Identifier: Apache-2.0
// vz_select.v — bit- and part-select writes to a forced vector.
`timescale 1ps/1ps
module VZSEL (output [2:0] Q, input C, input D, input R);
  reg [2:0] v;
  assign Q = v;
  always @(R)
    if (R) assign v = 3'b000;
    else deassign v;
  always @(posedge C) begin
    v[0] <= D;
    v[2:1] <= {D, ~D};
  end
endmodule
