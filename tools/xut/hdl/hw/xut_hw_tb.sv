// SPDX-License-Identifier: Apache-2.0
// Simulation testbench of the stepped harness (tools/xut/hw/hwsim.py). Plays host.memh
// into the harness's UART, writes every byte the harness transmits to harness_tx.txt
// (two hex digits per line), and observes the harness (common subset of xsim and Icarus):
// - XUT_MARGIN_VIOLATION: an in_vec or clock change closer than MON_MARGIN cycles to the
//   previous change, or a capture closer than MON_MARGIN cycles to the last change. A
//   capture is timed at the physical capture into cur_out, 2 cycles before the edge that
//   ends sample_take's cycle (xut_hw_ctrl's strobe timing), not at the strobe;
// - XUT_X_SAMPLE: an X or Z in the bits a SAMPLE captured from cur_out (the printer would
//   print it as 0);
// - XUT_X_TX: an X or Z in a byte the harness transmitted.
// The host side drives and samples on the falling clock edge, so it never races the
// harness's rising-edge logic.
//
// One command in flight (xut.hw.steps): host.memh, one 32-bit word per line: 000000bb
// sends byte bb; 1nnnnnnn waits until the harness has sent nnnnnnn newlines in total
// (the whole reply to every command so far); f0000000 ends the session.
`timescale 1ps / 1ps
`include "xut_hw_cfg.vh"
`include "host.vh"
module xut_hw_tb;
  localparam integer CPB = `XUT_HW_TB_CPB;          // hwsim.CPB, via host.vh
  localparam integer MON_MARGIN = `XUT_HW_TB_MON_MARGIN;
  localparam integer NHOST = `XUT_HOST_WORDS;
  reg clk = 1'b0;
  always #5000 clk = ~clk;                     // 100 MHz
  reg  rx = 1'b1;
  wire tx;
  wire [3:0] led;
  xut_hw_top #(.CLKS_PER_BIT(CPB)) u_top (
    .CLK100MHZ(clk), .uart_txd_in(rx), .uart_rxd_out(tx), .led(led));

  reg [31:0] host [0:NHOST-1];
  reg [63:0] cyc = 64'd0;
  integer    fd;
  integer    nl = 0;
  always @(posedge clk) cyc <= cyc + 64'd1;

  // ---- the harness's transmitter, decoded mid-bit
  reg [7:0] rbyte;
  integer   rk;
  initial begin
    fd = $fopen("harness_tx.txt", "w");
    forever begin
      @(negedge tx);
      repeat (CPB / 2) @(negedge clk);
      for (rk = 0; rk < 8; rk = rk + 1) begin
        repeat (CPB) @(negedge clk);
        rbyte[rk] = tx;
      end
      repeat (CPB) @(negedge clk);
      if (^rbyte === 1'bx) $display("XUT_X_TX cycle=%0d byte=%b", cyc, rbyte);
      $fwrite(fd, "%02x\n", rbyte);
      if (rbyte == 8'h0a) nl = nl + 1;
    end
  end

  // ---- the host
  task send_byte(input [7:0] v);
    integer j;
    begin
      @(negedge clk) rx = 1'b0;
      repeat (CPB) @(negedge clk);
      for (j = 0; j < 8; j = j + 1) begin
        rx = v[j];
        repeat (CPB) @(negedge clk);
      end
      rx = 1'b1;
      repeat (2 * CPB) @(negedge clk);
    end
  endtask

  integer i;
  initial begin : host_side
    $readmemh("host.memh", host);
    #(3_000_000);                              // 3 us: glbl's GSR and the harness's reset
    for (i = 0; i < NHOST; i = i + 1) begin
      if (host[i][31:28] == 4'h0) send_byte(host[i][7:0]);
      else if (host[i][31:28] == 4'h1) wait (nl >= host[i][27:0]);
    end
    repeat (8 * CPB) @(negedge clk);
    $fflush(fd);
    $display("XUT_DONE nl=%0d", nl);
    $finish;
  end

  // ---- a hung harness ends the run
  initial begin
    repeat (200_000_000) @(posedge clk);
    $display("XUT_TIMEOUT cycle=%0d nl=%0d", cyc, nl);
    $finish;
  end

  // ---- correctness by construction, observed (spec §7.1). At a posedge, cyc still holds
  // that edge's number: a commit/edge_we seen here changed the pins at this edge, and a
  // sample_take seen here means cur_out captured the DUT at edge cyc - 2.
  reg [63:0] last_change = 64'd0;
  reg        have_change = 1'b0;
  always @(posedge clk) begin
    if (u_top.u_ctrl.commit || u_top.u_ctrl.edge_we) begin
      if (have_change && (cyc - last_change) < MON_MARGIN)
        $display("XUT_MARGIN_VIOLATION change cycle=%0d last_change=%0d gap=%0d",
                 cyc, last_change, cyc - last_change);
      last_change <= cyc;
      have_change <= 1'b1;
    end
    if (u_top.u_ctrl.sample_take) begin
      if (have_change && (cyc - 64'd2 - last_change) < MON_MARGIN)
        $display("XUT_MARGIN_VIOLATION capture cycle=%0d last_change=%0d gap=%0d",
                 cyc - 64'd2, last_change, cyc - 64'd2 - last_change);
      if (^u_top.u_ctrl.p_bits === 1'bx)
        $display("XUT_X_SAMPLE cycle=%0d sidx=%0d bits=%b", cyc - 64'd2,
                 u_top.u_ctrl.p_sidx, u_top.u_ctrl.p_bits);
    end
  end
endmodule
