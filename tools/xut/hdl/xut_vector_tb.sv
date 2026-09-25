// SPDX-License-Identifier: Apache-2.0
// Generic vector testbench (spec §4.3, §5.3). Identical for every primitive:
// replays stim.memh (compiled from an .xvec by xut.stimcompile) and writes raw.txt.
// Portable subset of xsim, Icarus -g2012 and Verilator --timing.
//
// Semantics (shared with xut.golden.replay; pinned by tools/tests/test_stimcompile.py):
// - Every operation of one time step runs in this one process without yielding, so the
//   DUT wakes only after the whole step is applied. (The language lets a simulator
//   interleave processes at any statement; that it does not here holds in practice on
//   xsim, Icarus and Verilator; test_tb_simultaneous_edge_sees_new_data and the
//   golden-vs-simulator cross-checks would catch a change.) SETs go to a shadow
//   vector and are committed to in_vec in ONE assignment before any other operation
//   or time advance:
//   co-timed sets on disjoint bits are one atomic input change (ruling S6), and a
//   `simultaneous` group lands at one time step (a rising edge captures the new data).
// - Time 0: in_vec is x until every DUT process has started and waits (a barrier on a
//   non-blocking update at t=0); then the time-0 values (0, plus the `t=0 set` lines)
//   are applied as one change. UNISIM combinational models only react to input
//   changes, so this x -> value change is what makes their outputs defined.
// - glbl runs its own GSR start-up pulse (ROC_WIDTH); the stimulus starts after
//   settle_ps (xvec/validate), so nothing but the time-0 values happens before it.
// - A sample prints out_vec as it stands when the sample operation runs (validate
//   never lets a sample share its time with a change).
`timescale 1ps / 1ps
`include "xut_cfg.vh"
`include "stim.vh"

module xut_vector_tb;
  localparam integer NIN = `XUT_NIN;
  localparam integer NOUT = `XUT_NOUT;
  localparam integer NCLK = `XUT_NCLK;
  localparam integer MAXOPS = `XUT_MAXOPS;

  localparam [7:0] OP_SET = 8'd1, OP_EDGE = 8'd2, OP_GLBL = 8'd3, OP_SAMPLE = 8'd4,
                   OP_CLK_HI = 8'd5, OP_CLK_START = 8'd6, OP_CLK_STOP = 8'd7, OP_END = 8'd15;

  reg  [NIN-1:0]  in_vec;               // x until the time-0 barrier
  reg  [NIN-1:0]  in_nxt;               // pending SETs of the current time step
  reg  [NCLK-1:0] clk_step = {NCLK{1'b0}};
  reg  [NCLK-1:0] clk_free = {NCLK{1'b0}};
  reg  [NCLK-1:0] free_en = {NCLK{1'b0}};
  reg             t0_go = 1'b0;
  wire [NCLK-1:0] clk = clk_step | clk_free;
  wire [NOUT-1:0] out_vec;

  reg [127:0] ops [0:MAXOPS-1];
  reg [63:0]  hi_ps [0:NCLK-1];
  reg [63:0]  lo_ps [0:NCLK-1];

`ifdef XUT_GLBL_INSTANCE
  // Fallback for Verilator (Task 15, Step 1): glbl as an instance of the testbench,
  // found by UNISIM's upward name lookup and by the glbl.*_int writes below. (A line
  // comment must not START with the word Verilator: Verilator parses it as a pragma.)
  glbl glbl ();
`endif

  xut_dut dut (.clk(clk), .in_vec(in_vec), .out_vec(out_vec));

  genvar gi;
  generate
    for (gi = 0; gi < NCLK; gi = gi + 1) begin : g_free
      always begin
        wait (free_en[gi]);
        clk_free[gi] = 1'b1;
        #(hi_ps[gi]);
        clk_free[gi] = 1'b0;
        #(lo_ps[gi]);
      end
    end
  endgenerate

  function automatic [0:0] fourstate(input [1:0] v);
    case (v)
      2'd0: fourstate = 1'b0;
      2'd1: fourstate = 1'b1;
      2'd2: fourstate = 1'bx;
      default: fourstate = 1'bz;
    endcase
  endfunction

  integer fd, pc;
  reg         done = 1'b0;  // $finish need not stop this process at once (Verilator)
  reg [127:0] w;
  reg [7:0]   op;
  reg [23:0]  idx;
  reg [31:0]  val;
  reg [63:0]  t;

  initial begin
    in_nxt = {NIN{1'b0}};
    $readmemh("stim.memh", ops);
    fd = $fopen("raw.txt", "w");
    // Time-0 barrier: resume after the t=0 non-blocking update, when every DUT process
    // has run to its first event control. `wait`, not `@(posedge)`: Verilator may apply
    // the update before this process suspends, and an edge would then be missed.
    t0_go <= 1'b1;
    wait (t0_go);
    for (pc = 0; pc < MAXOPS && !done; pc = pc + 1) begin
      w = ops[pc];
      op = w[127:120];
      idx = w[119:96];
      val = w[95:64];
      t = w[63:0];
      if (op != OP_SET || t > $time) in_vec = in_nxt;  // commit the step's SETs at once
      if (t > $time) #(t - $time);
      case (op)
        OP_SET:       in_nxt[idx] = fourstate(val[1:0]);
        OP_EDGE:      clk_step[idx] = val[0];
        OP_GLBL: begin
          if (idx == 0) glbl.GSR_int = val[0];
          else if (idx == 1) glbl.GTS_int = val[0];
          else glbl.GRESTORE_int = val[0];
        end
        OP_SAMPLE:    $fdisplay(fd, "S %0d %b", idx, out_vec);
        OP_CLK_HI:    hi_ps[idx] = {32'd0, val};
        OP_CLK_START: begin lo_ps[idx] = {32'd0, val}; free_en[idx] = 1'b1; end
        OP_CLK_STOP:  free_en[idx] = 1'b0;
        OP_END: begin
          $fclose(fd);
          $display("XUT_DONE t=%0t", $time);
          done = 1'b1;
          $finish;
        end
        default: begin
          $display("XUT_ERROR bad op %0d at pc %0d", op, pc);
          done = 1'b1;
          $finish;
        end
      endcase
    end
    if (!done) begin
      $display("XUT_ERROR stimulus has no END operation");
      $finish;
    end
  end
endmodule
