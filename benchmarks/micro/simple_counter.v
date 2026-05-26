// Minimal Verilog benchmark — test BTOR2 bad property format only.
// Property: cnt should never be 8 (always true, 3-bit counter max=7).
// If pono returns 'unsat', the toolchain works.

module simple_counter (
    input clk,
    input reset,
    output bad
);
  reg [2:0] cnt;
  assign bad = (cnt == 3'd4);  // 3-bit counter, max=7, so 4 IS reachable

  always @(posedge clk) begin
    if (reset)
      cnt <= 3'd0;
    else
      cnt <= cnt + 3'd1;
  end
endmodule
