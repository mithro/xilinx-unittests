// SPDX-License-Identifier: Apache-2.0
// 7series.CFGLUT5.L1.sv_x_inputs. INIT is a module parameter; test.yaml sets it to all
// ones, so every documented check below holds whatever the (undocumented) bit order is.
// Checked (documented): every address reads 1 on O6, O5 and CDO (C1, C2); CE Low with
// CDI = x and CLK running leaves that unchanged (C4).
// Checkpoints only (UG953 does not define x behaviour): x on each I input (I<k>.x), one
// CE-High shift of CDI = x read at every address (S.a<n>), then CE = x (E.a0, E.a31).
`timescale 1ps / 1ps
module tb_cfglut5_x #(
    parameter [31:0] INIT = 32'hFFFF_FFFF
);
`include "xut_trace.svh"
  // Inputs start x and get their first values by a time-0 non-blocking update, as in
  // the vector testbench (a declaration initialiser can race the model at time 0).
  reg [4:0] I;
  reg CDI, CE, CLK;
  wire CDO, O5, O6;
  CFGLUT5 #(.INIT(INIT)) dut (
      .CDO(CDO), .O5(O5), .O6(O6), .CDI(CDI), .CE(CE), .CLK(CLK),
      .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4])
  );

  integer a, k;

  task automatic cycle;
    begin
      #4000 CLK = 1'b1;
      #5000 CLK = 1'b0;
      #1000;
    end
  endtask

  task automatic check_ones(input reg after_hold);
    integer b;
    begin
      for (b = 0; b < 32; b = b + 1) begin
        I = b;
        #1000;
        if (after_hold) begin
          `XUT_CHECKN("hold.O6.a", b, O6, 1'b1)
          `XUT_CHECKN("hold.O5.a", b, O5, 1'b1)
          `XUT_CHECKN("hold.CDO.a", b, CDO, 1'b1)
        end else begin
          `XUT_CHECKN("init.O6.a", b, O6, 1'b1)
          `XUT_CHECKN("init.O5.a", b, O5, 1'b1)
          `XUT_CHECKN("init.CDO.a", b, CDO, 1'b1)
        end
      end
    end
  endtask

  initial begin
    I <= 5'd0;
    CDI <= 1'b0;
    CE <= 1'b0;
    CLK <= 1'b0;
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    check_ones(1'b0);
    CE = 1'b0;  // C4: CE Low holds, even with CDI = x
    CDI = 1'bx;
    cycle;
    cycle;
    cycle;
    check_ones(1'b1);
    xut_open;
    for (k = 0; k < 5; k = k + 1) begin
      I = 5'd0;
      I[k] = 1'bx;
      #1000;
      $fdisplay(xut_fd, "I%0d.x  O6=%b O5=%b CDO=%b", k, O6, O5, CDO);
    end
    CE = 1'b1;  // one shift of an x bit
    cycle;
    CE = 1'b0;
    CDI = 1'b0;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "S.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    CE = 1'bx;  // CE = x with CDI = 0
    cycle;
    CE = 1'b0;
    I = 5'd0;
    #1000;
    $fdisplay(xut_fd, "E.a0  O6=%b O5=%b CDO=%b", O6, O5, CDO);
    I = 5'd31;
    #1000;
    $fdisplay(xut_fd, "E.a31  O6=%b O5=%b CDO=%b", O6, O5, CDO);
    xut_finish;
  end
endmodule
