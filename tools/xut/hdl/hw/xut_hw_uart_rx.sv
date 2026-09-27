// SPDX-License-Identifier: Apache-2.0
// 8N1 UART receiver: a two-flop synchroniser, then mid-bit sampling. A byte with a bad
// stop bit is dropped; the host then times out and retries the whole job (spec §7.5).
`timescale 1ps / 1ps
module xut_hw_uart_rx #(
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire       clk,
  input  wire       rst,
  input  wire       rx,
  output reg  [7:0] data = 8'h00,
  output reg        valid = 1'b0
);
  localparam integer CW = $clog2(CLKS_PER_BIT + 1);
  (* ASYNC_REG = "TRUE" *) reg [1:0] sync = 2'b11;
  wire r = sync[1];
  reg [CW-1:0] cnt = {CW{1'b0}};
  reg [3:0]    bitn = 4'd0;       // 0 idle; 1 start; 2..9 data; 10 stop
  reg [7:0]    sh = 8'h00;
  always @(posedge clk) begin
    sync <= {sync[0], rx};
    valid <= 1'b0;
    if (rst) begin
      bitn <= 4'd0;
    end else if (bitn == 4'd0) begin
      if (!r) begin
        bitn <= 4'd1;
        cnt <= CLKS_PER_BIT / 2 - 1;   // to the middle of the start bit
      end
    end else if (cnt != {CW{1'b0}}) begin
      cnt <= cnt - 1'b1;
    end else begin
      cnt <= CLKS_PER_BIT - 1;
      if (bitn == 4'd1) begin
        bitn <= r ? 4'd0 : 4'd2;       // high at mid-start: a glitch, not a start bit
      end else if (bitn <= 4'd9) begin
        sh <= {r, sh[7:1]};
        bitn <= bitn + 4'd1;
      end else begin
        if (r) begin
          data <= sh;
          valid <= 1'b1;
        end
        bitn <= 4'd0;
      end
    end
  end
endmodule
