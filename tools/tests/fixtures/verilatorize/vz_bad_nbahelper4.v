// SPDX-License-Identifier: Apache-2.0
// vz_bad_nbahelper4.v — vz_bad_nbacone.v (VZCE) with its NBA stage moved into a same-file
// helper instance (the reviewer's VZCES): Icarus showed 0 diffs, Verilator 1036 (PR #10 review).
`timescale 1ps/1ps
module VZCES (output [3:0] Q, input C, input D, input R);
  reg [3:0] q;
  wire r;
  assign Q = q;
  vzce_stage st (.y(r), .c(C), .a(R));
  always @(r)
    if (r) assign q = 4'ha;
    else deassign q;
  always @(posedge C) begin
    q[0] <= D;
    q[3:1] <= {q[2:0]};
  end
  always @(negedge C) q[2] <= ~D;
endmodule
module vzce_stage (output y, input c, input a);
  reg q;
  assign y = q;
  always @(posedge c) q <= a;
endmodule
