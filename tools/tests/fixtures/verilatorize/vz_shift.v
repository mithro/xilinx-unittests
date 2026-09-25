// SPDX-License-Identifier: Apache-2.0
// vz_shift.v — a self-referencing write (shift chain reads data while writing it).
`timescale 1ps/1ps
module VZSHIFT (output Q, input C, input D, input R);
  reg [3:0] data;
  assign Q = data[3];
  always @(R)
    if (R) assign data = 4'b0000;
    else deassign data;
  always @(posedge C) data <= {data[2:0], D};
endmodule
