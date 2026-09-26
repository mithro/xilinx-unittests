// SPDX-License-Identifier: Apache-2.0
// vz_fresh.v — the forced reg is read right after an ordinary blocking write in the same
// block (BUFR/FIFO18E1/MMCME2_ADV-style): the read must see the value just written, not the
// net X, which follows X__base only later in the time step.
`timescale 1ps/1ps
module VZFRESH (output [3:0] Q, output [3:0] Y, output Z, input C, input R, input E);
  reg [3:0] cnt;
  reg [3:0] y;
  reg z;
  initial cnt = 4'd5;
  assign Q = cnt;
  assign Y = y;
  assign Z = z;
  always @(R)
    if (R) assign cnt = 4'd0;
    else deassign cnt;
  always @(posedge C) begin
    if (E) cnt = cnt + 1;
    y = cnt;
    if (cnt[0]) z = 1'b1;
    else z = 1'b0;
  end
endmodule
