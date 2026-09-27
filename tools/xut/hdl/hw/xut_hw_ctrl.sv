// SPDX-License-Identifier: Apache-2.0
// Stepped fabric harness controller (spec §7.1): UART command parser, program loader,
// stimulus BRAM, sequencer and message printer. Protocol: xut.hw.proto. Reference model:
// xut.hw.interp.Harness, which must predict this module's UART output byte for byte
// (tools/tests/test_hw_rtl.py).
//
// One command in flight (xut.hw.proto): the host sends the next command only after the
// whole reply to the previous one (for R, through the end line). There is no receive
// FIFO: rx bytes are read only in S_IDLE and S_LD_*, and a byte that arrives while the
// harness prints or runs is discarded. The printer's done (so the return to S_IDLE)
// comes when the UART accepts the final newline, a byte time before the host has it.
//
// A lost or garbled host byte leaves the loader waiting in S_LD_* for bytes that never
// come; later command bytes are then taken as program data and the session times out.
// There is deliberately no inter-byte timeout: the host treats any timeout as a
// transport error, and every retry reprograms the FPGA, which resets this state.
//
// Correctness by construction: after every COMMIT (the selected slot's in_vec takes
// in_nxt) and every EDGE (one of its clock flip-flops changes), S_WAITM holds MARGIN + 1
// cycles before the next word, so no two changes and no change and capture are closer
// than MARGIN cycles, whatever the program says.
//
// Strobe timing, for a monitor of commit, edge_we and sample_take (all registered, set
// at the DECODE edge):
// - commit and edge_we are high in the cycle that ends at the edge where the slot's
//   in_vec or clock flip-flop changes;
// - sample_take is high in the cycle after the DECODE edge E that copies cur_out into
//   p_bits, and cur_out took the DUT's out_vec at edge E-1. So the physical capture is
//   2 cycles before the edge that ends sample_take's cycle: a monitor must measure
//   change-to-capture as (sample_take edge - 2) - change edge, which is MARGIN + 1 at
//   its shortest (strobe to strobe: MARGIN + 3).
`timescale 1ps / 1ps
module xut_hw_ctrl #(
  parameter [31:0] BUILD_ID = 32'h00000000,
  parameter integer NSLOTS = 2,
  parameter integer MAXIN = 16,          // a multiple of 16
  parameter integer MAXOUT = 16,
  parameter integer MAXWORDS = 8192,
  parameter integer MARGIN = 16,
  parameter integer CLKS_PER_BIT = 868
) (
  input  wire              clk,
  input  wire              rst,
  input  wire              uart_rx,
  output wire              uart_tx,
  output reg  [7:0]        sel = 8'd0,
  output reg               commit = 1'b0,
  output reg  [MAXIN-1:0]  in_nxt = {MAXIN{1'b0}},
  output reg               edge_we = 1'b0,
  output reg  [11:0]       edge_idx = 12'd0,
  output reg               edge_val = 1'b0,
  output reg               sample_take = 1'b0,
  input  wire [MAXIN-1:0]  cur_in,
  input  wire [MAXOUT-1:0] cur_out,
  input  wire [15:0]       cur_noutw,
  output wire [3:0]        leds
);
  `include "xut_hw_crc32.vh"
  `include "xut_hw_msgs.vh"
  localparam integer AW = $clog2(MAXWORDS);
  localparam integer NCHUNK = MAXIN / 16;
  localparam [7:0]  NSLOTS8 = NSLOTS;
  localparam [15:0] MAXWORDS16 = MAXWORDS;
  localparam [7:0]  MARGIN8 = MARGIN;
  localparam [7:0] ST_OK = 8'd0, ST_USED = 8'd1, ST_NOLOAD = 8'd2, ST_BADOP = 8'd3,
                   ST_BADSLOT = 8'd4, ST_BADCRC = 8'd5, ST_TOOLONG = 8'd6, ST_BADCMD = 8'd7;

  // ---- UART
  wire [7:0] rx_data;
  wire       rx_valid;
  wire [7:0] tx_data;
  wire       tx_valid, tx_ready;
  xut_hw_uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
    .clk(clk), .rst(rst), .rx(uart_rx), .data(rx_data), .valid(rx_valid));
  xut_hw_uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
    .clk(clk), .rst(rst), .data(tx_data), .valid(tx_valid), .ready(tx_ready), .tx(uart_tx));

  // ---- printer and its fields (held stable while it prints)
  reg              p_start = 1'b0;
  reg  [2:0]       p_msg = 3'd0;
  reg  [7:0]       p_slot = 8'd0, p_status = 8'd0, p_cmd = 8'd0;
  reg  [15:0]      p_words = 16'd0, p_samples = 16'd0, p_sidx = 16'd0;
  reg  [31:0]      p_crc = 32'd0;
  reg  [MAXOUT-1:0] p_bits = {MAXOUT{1'b0}};
  wire             p_done, p_sent;
  xut_hw_print #(.MAXOUT(MAXOUT)) u_print (
    .clk(clk), .rst(rst), .start(p_start), .msg(p_msg), .done(p_done), .sent(p_sent),
    .f_build(BUILD_ID), .f_slots(NSLOTS8), .f_maxwords(MAXWORDS16), .f_margin(MARGIN8),
    .f_slot(p_slot), .f_words(p_words), .f_crc(p_crc), .f_status(p_status),
    .f_samples(p_samples), .f_sidx(p_sidx), .f_bits(p_bits), .f_nbits(cur_noutw),
    .f_cmd(p_cmd), .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready));

  // ---- stimulus memory: inferred block RAM, one write port, one registered read port
  reg [31:0]   mem [0:MAXWORDS-1];
  reg [31:0]   rdata = 32'd0;
  reg          mem_we = 1'b0;
  reg [AW-1:0] mem_wa = {AW{1'b0}};
  reg [31:0]   mem_wd = 32'd0;
  reg [15:0]   pc = 16'd0;
  always @(posedge clk) begin
    if (mem_we) mem[mem_wa] <= mem_wd;
    rdata <= mem[pc[AW-1:0]];
  end

  // ---- state
  localparam [4:0] S_IDLE = 5'd0, S_PRINT = 5'd1, S_LD_SLOT = 5'd2, S_LD_N0 = 5'd3,
                   S_LD_N1 = 5'd4, S_LD_W = 5'd5, S_LD_CRC = 5'd6, S_LD_DONE = 5'd7,
                   S_RUN = 5'd8, S_RUN_GO = 5'd9, S_FETCH = 5'd10, S_DECODE = 5'd11,
                   S_WAITM = 5'd12, S_SAMPLED = 5'd13, S_END = 5'd14;
  reg [4:0]  st = S_IDLE, after = S_IDLE;
  reg [31:0] crc = 32'hFFFFFFFF;        // load CRC state
  reg [31:0] rcrc = 32'hFFFFFFFF;       // run-output CRC state
  reg        rcrc_on = 1'b0;
  reg [7:0]  ld_slot = 8'd0;
  reg [15:0] ld_n = 16'd0, ld_i = 16'd0;
  reg [1:0]  ld_b = 2'd0;
  reg [31:0] ld_word = 32'd0;
  reg        loaded = 1'b0;
  reg [7:0]  lslot = 8'd0;
  reg [15:0] lwords = 16'd0;
  reg [NSLOTS-1:0] used = {NSLOTS{1'b0}};
  reg [15:0] samples = 16'd0;
  reg [27:0] wcnt = 28'd0;
  reg        err_seen = 1'b0;
  reg [25:0] hb = 26'd0;
  integer    c;
  wire [3:0] op = rdata[31:28];
  wire       ld_ok = (ld_slot < NSLOTS) && (ld_n != 16'd0) && (ld_n <= MAXWORDS) &&
                     (ld_word == ~crc);

  always @(posedge clk) hb <= hb + 26'd1;
  assign leds = {err_seen, st != S_IDLE, loaded, hb[25]};

  always @(posedge clk) begin
    p_start <= 1'b0;
    commit <= 1'b0;
    edge_we <= 1'b0;
    sample_take <= 1'b0;
    mem_we <= 1'b0;
    if (p_sent && rcrc_on) rcrc <= xut_crc32_byte(rcrc, tx_data);
    if (rst) begin
      st <= S_IDLE;
      loaded <= 1'b0;
      used <= {NSLOTS{1'b0}};
      rcrc_on <= 1'b0;
    end else case (st)
      S_IDLE: if (rx_valid) begin
        if (rx_data == 8'h49) begin                        // "I"
          p_msg <= XUT_MSG_ID; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
        end else if (rx_data == 8'h4C) begin               // "L"
          crc <= 32'hFFFFFFFF; st <= S_LD_SLOT;
        end else if (rx_data == 8'h52) begin               // "R"
          st <= S_RUN;
        end else begin
          p_cmd <= rx_data; p_status <= ST_BADCMD; err_seen <= 1'b1;
          p_msg <= XUT_MSG_ERR; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
        end
      end
      S_PRINT: if (p_done) st <= after;
      S_LD_SLOT: if (rx_valid) begin
        ld_slot <= rx_data; crc <= xut_crc32_byte(crc, rx_data); st <= S_LD_N0;
      end
      S_LD_N0: if (rx_valid) begin
        ld_n[7:0] <= rx_data; crc <= xut_crc32_byte(crc, rx_data); st <= S_LD_N1;
      end
      S_LD_N1: if (rx_valid) begin
        ld_n[15:8] <= rx_data; crc <= xut_crc32_byte(crc, rx_data);
        ld_i <= 16'd0; ld_b <= 2'd0;
        st <= ({rx_data, ld_n[7:0]} == 16'd0) ? S_LD_CRC : S_LD_W;
      end
      S_LD_W: if (rx_valid) begin
        crc <= xut_crc32_byte(crc, rx_data);
        ld_word <= {rx_data, ld_word[31:8]};              // little-endian
        ld_b <= ld_b + 2'd1;
        if (ld_b == 2'd3) begin
          if (ld_i < MAXWORDS) begin
            mem_we <= 1'b1; mem_wa <= ld_i[AW-1:0]; mem_wd <= {rx_data, ld_word[31:8]};
          end
          ld_i <= ld_i + 16'd1;
          if (ld_i + 16'd1 == ld_n) st <= S_LD_CRC;
        end
      end
      S_LD_CRC: if (rx_valid) begin
        ld_word <= {rx_data, ld_word[31:8]};
        ld_b <= ld_b + 2'd1;
        if (ld_b == 2'd3) st <= S_LD_DONE;
      end
      S_LD_DONE: begin
        p_slot <= ld_slot; p_words <= ld_n; p_crc <= ~crc;
        if (ld_slot >= NSLOTS) p_status <= ST_BADSLOT;
        else if (ld_n == 16'd0 || ld_n > MAXWORDS) p_status <= ST_TOOLONG;
        else if (ld_word != ~crc) p_status <= ST_BADCRC;
        else p_status <= ST_OK;
        loaded <= ld_ok;
        if (ld_ok) begin
          lslot <= ld_slot; lwords <= ld_n;
        end else begin
          err_seen <= 1'b1;
        end
        p_msg <= XUT_MSG_LOAD; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
      end
      S_RUN: begin
        sel <= lslot; p_slot <= lslot; p_words <= lwords;
        rcrc <= 32'hFFFFFFFF; rcrc_on <= 1'b1; samples <= 16'd0;
        p_msg <= XUT_MSG_RUN; p_start <= 1'b1; after <= S_RUN_GO; st <= S_PRINT;
      end
      S_RUN_GO: begin
        if (!loaded) begin
          p_status <= ST_NOLOAD; st <= S_END;
        end else if (used[lslot]) begin
          p_status <= ST_USED; st <= S_END;
        end else begin
          used[lslot] <= 1'b1; in_nxt <= cur_in; pc <= 16'd0; st <= S_FETCH;
        end
      end
      S_FETCH: st <= S_DECODE;                              // rdata <= mem[pc] at this edge
      S_DECODE: begin
        if (pc >= lwords) begin
          p_status <= ST_BADOP; st <= S_END;                // ran past the last word
        end else case (op)
          4'h1: begin                                       // SET
            for (c = 0; c < NCHUNK; c = c + 1)
              if (rdata[27:16] == c) in_nxt[16 * c +: 16] <= rdata[15:0];
            pc <= pc + 16'd1; st <= S_FETCH;
          end
          4'h2: begin                                       // COMMIT
            commit <= 1'b1; wcnt <= MARGIN; st <= S_WAITM;
          end
          4'h3: begin                                       // EDGE
            edge_we <= 1'b1; edge_idx <= rdata[11:0]; edge_val <= rdata[12];
            wcnt <= MARGIN; st <= S_WAITM;
          end
          4'h4: begin                                       // WAIT
            wcnt <= rdata[27:0]; st <= S_WAITM;
          end
          4'h5: begin                                       // SAMPLE
            sample_take <= 1'b1; p_bits <= cur_out; p_sidx <= samples;
            samples <= samples + 16'd1;
            p_msg <= XUT_MSG_SAMPLE; p_start <= 1'b1; after <= S_SAMPLED; st <= S_PRINT;
          end
          4'hF: begin                                       // END
            p_status <= ST_OK; st <= S_END;
          end
          default: begin
            p_status <= ST_BADOP; st <= S_END;
          end
        endcase
      end
      S_WAITM: begin
        if (wcnt == 28'd0) begin
          pc <= pc + 16'd1; st <= S_FETCH;
        end else begin
          wcnt <= wcnt - 28'd1;
        end
      end
      S_SAMPLED: begin
        pc <= pc + 16'd1; st <= S_FETCH;
      end
      S_END: begin
        rcrc_on <= 1'b0; p_crc <= ~rcrc; p_samples <= samples;
        if (p_status != ST_OK) err_seen <= 1'b1;
        p_msg <= XUT_MSG_END; p_start <= 1'b1; after <= S_IDLE; st <= S_PRINT;
      end
      default: st <= S_IDLE;
    endcase
  end
endmodule
