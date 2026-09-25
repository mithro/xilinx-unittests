// SPDX-License-Identifier: Apache-2.0
// Checkpoint trace + self-check helpers for hand-written SV testbenches (spec §4.3).
// Include inside the module body. Lines written: "<label>  <port>=<bits>" (.xtr body).
`ifndef XUT_TRACE_SVH
`define XUT_TRACE_SVH
`define XUT_CHECK(label, sig, exp) \
  if ((sig) !== (exp)) begin \
    xut_errors = xut_errors + 1; \
    $display("XUT_FAIL %s: got %b expected %b at %0t", label, sig, exp, $time); \
  end
`define XUT_CHECKN(label, n, sig, exp) \
  if ((sig) !== (exp)) begin \
    xut_errors = xut_errors + 1; \
    $display("XUT_FAIL %s%0d: got %b expected %b at %0t", label, n, sig, exp, $time); \
  end
`define XUT_POINT1(label, p1, s1) $fdisplay(xut_fd, "%s  %s=%b", label, p1, s1);
`define XUT_POINT2(label, p1, s1, p2, s2) $fdisplay(xut_fd, "%s  %s=%b %s=%b", label, p1, s1, p2, s2);
`endif
integer xut_fd;
integer xut_errors;
`ifdef XUT_GLBL_INSTANCE
// Fallback for Verilator (Task 15, Step 1): glbl as an instance of the testbench, found
// by UNISIM's upward name lookup and by this testbench's own glbl.GSR_int writes. (A
// line comment must not START with the word Verilator: Verilator parses it as a pragma.)
glbl glbl ();
`endif
initial begin
  xut_errors = 0;
  xut_fd = $fopen("trace.body", "w");
end
task automatic xut_finish;
  begin
    $fclose(xut_fd);
    if (xut_errors == 0) $display("XUT_PASS");
    else $display("XUT_FAIL %0d check(s) failed", xut_errors);
    $finish;
  end
endtask
