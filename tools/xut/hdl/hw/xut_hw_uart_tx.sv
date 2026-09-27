// SPDX-License-Identifier: Apache-2.0
// 8N1 UART transmitter: start bit, 8 data bits LSB first, stop bit.
// A byte is accepted in the cycle where valid && ready.
`timescale 1ps / 1ps
module xut_hw_uart_tx #(
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire       clk,
  input  wire       rst,
  input  wire [7:0] data,
  input  wire       valid,
  output wire       ready,
  output reg        tx = 1'b1
);
  localparam integer CW = $clog2(CLKS_PER_BIT + 1);
  reg [CW-1:0] cnt = {CW{1'b0}};
  reg [3:0]    bitn = 4'd0;       // 0 idle; 1 start; 2..9 data; 10 stop
  reg [8:0]    shreg = 9'h1FF;    // {stop, d7..d0}
  assign ready = (bitn == 4'd0);
  always @(posedge clk) begin
    if (rst) begin
      tx <= 1'b1;
      bitn <= 4'd0;
      cnt <= {CW{1'b0}};
    end else if (bitn == 4'd0) begin
      if (valid) begin
        shreg <= {1'b1, data};
        tx <= 1'b0;
        bitn <= 4'd1;
        cnt <= CLKS_PER_BIT - 1;
      end
    end else if (cnt != {CW{1'b0}}) begin
      cnt <= cnt - 1'b1;
    end else if (bitn == 4'd10) begin
      bitn <= 4'd0;
    end else begin
      tx <= shreg[0];
      shreg <= {1'b1, shreg[8:1]};
      bitn <= bitn + 4'd1;
      cnt <= CLKS_PER_BIT - 1;
    end
  end
endmodule
