// SPDX-License-Identifier: Apache-2.0
// vz_cone.v — the forcing block is sensitive to rst_int, a register fed by RST|PWRDWN.
`timescale 1ps/1ps
module MMCMVZ (output LOCKED, input CLKIN1, input RST, input PWRDWN);
  wire rst_input = RST | PWRDWN;
  reg rst_int;
  reg locked;
  assign LOCKED = locked;
  always @(posedge CLKIN1 or posedge rst_input)
    if (rst_input) rst_int <= 1'b1;
    else rst_int <= 1'b0;
  always @(rst_int)
    if (rst_int) assign locked = 1'b0;
    else deassign locked;
  always @(posedge CLKIN1) locked <= 1'b1;
endmodule
