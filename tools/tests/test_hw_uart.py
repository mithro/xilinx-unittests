# SPDX-License-Identifier: Apache-2.0
"""The harness UART receiver on Icarus: after a framing error it waits for the line to go
idle before it re-arms, so a break that ends in the middle of where a next frame would
be yields no byte (ruling S59 minor 7)."""

import shutil

import pytest

from xut.hw.slots import HW_HDL

CPB = 8  # clocks per bit

TB = f"""// SPDX-License-Identifier: Apache-2.0
`timescale 1ns / 1ps
module tb;
  reg clk = 1'b0, rx = 1'b1;
  wire [7:0] data;
  wire valid;
  always #5 clk = ~clk;
  xut_hw_uart_rx #(.CLKS_PER_BIT({CPB})) u (
    .clk(clk), .rst(1'b0), .rx(rx), .data(data), .valid(valid));
  always @(posedge clk) if (valid) $display("BYTE %02x", data);
  task bits(input integer n, input v);
    begin rx = v; repeat (n * {CPB}) @(posedge clk); end
  endtask
  task frame(input [7:0] b, input stop);
    integer i;
    begin
      bits(1, 1'b0);
      for (i = 0; i < 8; i = i + 1) bits(1, b[i]);
      bits(1, stop);
    end
  endtask
  initial begin
    bits(4, 1'b1);
    frame(8'h5a, 1'b0);   // a framing error (stop bit low) ...
    bits(5, 1'b0);        // ... then a break that ends mid-way through a would-be frame
    bits(12, 1'b1);
    frame(8'ha5, 1'b1);   // a good byte
    bits(4, 1'b1);
    $display("DONE");
    $finish;
  end
endmodule
"""


@pytest.mark.container
def test_rx_rearms_only_after_the_line_is_idle(tmp_path):
    from xut.container import executor_for
    from xut.modelsrc import resolve

    ms = resolve("auto")
    d = tmp_path / "uart"
    d.mkdir()
    shutil.copy(HW_HDL / "xut_hw_uart_rx.sv", d / "xut_hw_uart_rx.sv")
    (d / "tb.sv").write_text(TB)
    ex = executor_for(ms, tmp_path)
    vvp = ex.guest(d / "tb.vvp")
    argv = ["iverilog", "-g2012", "-Wall", "-o", vvp, "-s", "tb"]
    argv += [ex.guest(d / "xut_hw_uart_rx.sv"), ex.guest(d / "tb.sv")]
    assert ex.run(argv, cwd=d, log=d / "build.log", timeout_s=300) == 0, (
        d / "build.log"
    ).read_text()
    assert ex.run(["vvp", "-n", vvp], cwd=d, log=d / "sim.log", timeout_s=300) == 0
    text = (d / "sim.log").read_text()
    assert "DONE" in text, text
    assert [ln.split()[1] for ln in text.splitlines() if ln.startswith("BYTE ")] == ["a5"], text
