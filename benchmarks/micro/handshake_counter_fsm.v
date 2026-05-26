// Controlled micro-benchmark v2: single clear property
// Designed to produce multi-state relational lemmas for LLM generalization.

module handshake_counter_fsm (
    input clk,
    input reset,
    input start,
    input ready,
    output bad
);

  localparam IDLE = 2'd0;
  localparam RUN  = 2'd1;
  localparam DONE = 2'd2;

  reg [1:0] state;
  reg [2:0] cnt;
  reg valid;
  reg busy;
  reg almost_done;

  always @(posedge clk) begin
    if (reset) begin
      state       <= IDLE;
      cnt         <= 3'd0;
      valid       <= 1'b0;
      busy        <= 1'b0;
      almost_done <= 1'b0;
    end else begin
      almost_done <= 1'b0;

      case (state)
        IDLE: begin
          cnt   <= 3'd0;
          valid <= 1'b0;
          busy  <= 1'b0;
          if (start) begin
            state <= RUN;
            busy  <= 1'b1;
          end
        end

        RUN: begin
          valid <= 1'b1;
          busy  <= 1'b1;

          if (cnt == 3'd3)
            almost_done <= 1'b1;

          if (ready) begin
            if (cnt == 3'd4) begin
              state <= DONE;
            end else begin
              cnt <= cnt + 3'd1;
            end
          end
        end

        DONE: begin
          valid <= 1'b0;
          busy  <= 1'b0;
          state <= IDLE;
          cnt   <= 3'd0;
        end

        default: begin
          state       <= IDLE;
          cnt         <= 3'd0;
          valid       <= 1'b0;
          busy        <= 1'b0;
          almost_done <= 1'b0;
        end
      endcase
    end
  end

  // Single property: valid always implies busy
  // This SHOULD be an invariant, making the design safe.
  wire prop1_violated = valid && !busy;
  assign bad = prop1_violated;

endmodule
