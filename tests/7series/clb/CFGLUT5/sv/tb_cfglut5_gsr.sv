// SPDX-License-Identifier: Apache-2.0
// 7series.CFGLUT5.L1.sv_gsr_midsim. INIT is a module parameter; test.yaml sets all ones.
// Checked (documented, whatever the undocumented bit order): all ones read 1 everywhere
// (C1, C6); 32 CE-High shifts of 0 replace the whole function, so every address then
// reads 0 (C3); 32 shifts of 1 after the GSR pulse read 1 everywhere again.
// Checkpoints only (UG953 names no GSR effect on CFGLUT5): every address while GSR is
// high (G.hi.a<n>) and after it falls (G.lo.a<n>): is INIT reloaded, or the zeros kept?
`timescale 1ps / 1ps
module tb_cfglut5_gsr #(
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

  integer a;

  task automatic cycle;
    begin
      #4000 CLK = 1'b1;
      #5000 CLK = 1'b0;
      #1000;
    end
  endtask

  task automatic reload(input reg bit_value);
    integer s;
    begin
      CE = 1'b1;
      CDI = bit_value;
      for (s = 0; s < 32; s = s + 1) cycle;
      CE = 1'b0;
    end
  endtask

  initial begin
    I <= 5'd0;
    CDI <= 1'b0;
    CE <= 1'b0;
    CLK <= 1'b0;
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("init.O6.a", a, O6, 1'b1)
    end
    reload(1'b0);
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("zero.O6.a", a, O6, 1'b0)
      `XUT_CHECKN("zero.O5.a", a, O5, 1'b0)
      `XUT_CHECKN("zero.CDO.a", a, CDO, 1'b0)
    end
    glbl.GSR_int = 1'b1;
    #1000;
    xut_open;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "G.hi.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    glbl.GSR_int = 1'b0;
    #1000;
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      $fdisplay(xut_fd, "G.lo.a%0d  O6=%b O5=%b CDO=%b", a, O6, O5, CDO);
    end
    reload(1'b1);
    for (a = 0; a < 32; a = a + 1) begin
      I = a;
      #1000;
      `XUT_CHECKN("one.O6.a", a, O6, 1'b1)
    end
    xut_finish;
  end
endmodule
