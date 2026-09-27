// SPDX-License-Identifier: Apache-2.0
// Prints one message of xut.hw.proto.MESSAGES from the generated ROM (xut_hw_msgs.vh):
// ASCII bytes are sent as they are; a field token is replaced by its value, in fixed-width
// lower-case hex, or in binary (MSB first, f_nbits wide) for `bits`. `sent` pulses once
// per byte the UART accepted (the controller's run CRC); `done` pulses at the end.
// Field values must stay stable until `done`.
`timescale 1ps / 1ps
module xut_hw_print #(
  parameter integer MAXOUT = 16
) (
  input  wire              clk,
  input  wire              rst,
  input  wire              start,
  input  wire [2:0]        msg,
  output reg               done = 1'b0,
  output reg               sent = 1'b0,
  input  wire [31:0]       f_build,
  input  wire [7:0]        f_slots,
  input  wire [15:0]       f_maxwords,
  input  wire [7:0]        f_margin,
  input  wire [7:0]        f_slot,
  input  wire [15:0]       f_words,
  input  wire [31:0]       f_crc,
  input  wire [7:0]        f_status,
  input  wire [15:0]       f_samples,
  input  wire [15:0]       f_sidx,
  input  wire [MAXOUT-1:0] f_bits,
  input  wire [15:0]       f_nbits,
  input  wire [7:0]        f_cmd,
  output reg  [7:0]        tx_data = 8'h00,
  output reg               tx_valid = 1'b0,
  input  wire              tx_ready
);
  `include "xut_hw_msgs.vh"
  localparam [1:0] S_IDLE = 2'd0, S_TOK = 2'd1, S_FIELD = 2'd2, S_OUT = 2'd3;
  reg [1:0]  st = S_IDLE;
  reg [8:0]  pc = 9'd0;
  reg [3:0]  fld = 4'd0;
  reg [15:0] d = 16'd0;          // the digit (or bit) being printed, counting down
  reg        in_field = 1'b0;
  wire [7:0] tok = xut_hw_msg_rom(pc);

  reg [31:0] fv;
  always @* begin
    case (fld)
      XUT_F_BUILD:    fv = f_build;
      XUT_F_SLOTS:    fv = {24'd0, f_slots};
      XUT_F_MAXWORDS: fv = {16'd0, f_maxwords};
      XUT_F_MARGIN:   fv = {24'd0, f_margin};
      XUT_F_SLOT:     fv = {24'd0, f_slot};
      XUT_F_WORDS:    fv = {16'd0, f_words};
      XUT_F_CRC:      fv = f_crc;
      XUT_F_STATUS:   fv = {24'd0, f_status};
      XUT_F_SAMPLES:  fv = {16'd0, f_samples};
      XUT_F_SIDX:     fv = {16'd0, f_sidx};
      XUT_F_CMD:      fv = {24'd0, f_cmd};
      default:        fv = 32'd0;
    endcase
  end
  wire [3:0] nib = fv[4 * d[2:0] +: 4];
  wire [7:0] hexc = (nib < 4'd10) ? (8'h30 + {4'h0, nib}) : (8'h57 + {4'h0, nib});

  always @(posedge clk) begin
    done <= 1'b0;
    sent <= 1'b0;
    if (rst) begin
      st <= S_IDLE;
      tx_valid <= 1'b0;
    end else case (st)
      S_IDLE: if (start) begin
        pc <= xut_hw_msg_start(msg);
        st <= S_TOK;
      end
      S_TOK: begin
        if (tok == 8'h00) begin
          done <= 1'b1;
          st <= S_IDLE;
        end else if (tok[7]) begin
          fld <= tok[3:0];
          d <= xut_hw_field_digits(tok[3:0], f_nbits) - 16'd1;
          pc <= pc + 9'd1;
          st <= S_FIELD;
        end else begin
          tx_data <= tok;
          tx_valid <= 1'b1;
          in_field <= 1'b0;
          pc <= pc + 9'd1;
          st <= S_OUT;
        end
      end
      S_FIELD: begin
        if (fld == XUT_F_BITS) begin
          if (f_bits[d]) tx_data <= 8'h31;   // an x in simulation prints '0', as 2-state silicon would
          else tx_data <= 8'h30;
        end else begin
          tx_data <= hexc;
        end
        tx_valid <= 1'b1;
        in_field <= 1'b1;
        st <= S_OUT;
      end
      S_OUT: if (tx_ready) begin
        tx_valid <= 1'b0;
        sent <= 1'b1;
        if (in_field && d != 16'd0) begin
          d <= d - 16'd1;
          st <= S_FIELD;
        end else begin
          st <= S_TOK;
        end
      end
    endcase
  end
endmodule
