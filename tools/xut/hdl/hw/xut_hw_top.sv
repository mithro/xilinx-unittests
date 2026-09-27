// SPDX-License-Identifier: Apache-2.0
// Stepped fabric harness top for the Arty A7-35T (spec §7.1). The system clock is the
// board's 100 MHz oscillator through one BUFG; a power-on counter holds the controller
// in reset for 128 cycles after configuration. xut_hw_slots and xut_hw_cfg.vh are
// generated per bitstream by xut.hw.slots.
`timescale 1ps / 1ps
`include "xut_hw_cfg.vh"
module xut_hw_top #(
  parameter integer CLKS_PER_BIT = 868      // 100 MHz / 115200 baud
) (
  input  wire       CLK100MHZ,
  input  wire       uart_txd_in,            // host -> FPGA
  output wire       uart_rxd_out,           // FPGA -> host
  output wire [3:0] led
);
  localparam integer MAXIN = `XUT_HW_MAXIN;
  localparam integer MAXOUT = `XUT_HW_MAXOUT;
  wire clk;
  BUFG u_sysclk (.I(CLK100MHZ), .O(clk));
  reg [7:0] por = 8'd0;
  always @(posedge clk) if (!por[7]) por <= por + 8'd1;
  wire rst = !por[7];

  wire [7:0]        sel;
  wire              commit, edge_we, edge_val, sample_take;
  wire [11:0]       edge_idx;
  wire [MAXIN-1:0]  in_nxt, cur_in;
  wire [MAXOUT-1:0] cur_out;
  wire [15:0]       cur_noutw;
  xut_hw_ctrl #(
    .BUILD_ID(`XUT_HW_BUILD_ID), .NSLOTS(`XUT_HW_NSLOTS), .MAXIN(MAXIN), .MAXOUT(MAXOUT),
    .MAXWORDS(`XUT_HW_MAXWORDS), .MARGIN(`XUT_HW_MARGIN), .CLKS_PER_BIT(CLKS_PER_BIT)
  ) u_ctrl (
    .clk(clk), .rst(rst), .uart_rx(uart_txd_in), .uart_tx(uart_rxd_out),
    .sel(sel), .commit(commit), .in_nxt(in_nxt), .edge_we(edge_we), .edge_idx(edge_idx),
    .edge_val(edge_val), .sample_take(sample_take), .cur_in(cur_in), .cur_out(cur_out),
    .cur_noutw(cur_noutw), .leds(led));
  xut_hw_slots u_slots (
    .clk(clk), .sel(sel), .commit(commit), .in_nxt(in_nxt), .edge_we(edge_we),
    .edge_idx(edge_idx), .edge_val(edge_val), .cur_in(cur_in), .cur_out(cur_out),
    .cur_noutw(cur_noutw));
endmodule
