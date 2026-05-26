// Controlled benchmark v2: Credit counter (lemma-critical)
// Property: bad = (credit == 0) && (mode == ACTIVE) && send_req
// This SHOULD be unreachable (safe) IF the invariant
// 'credit never drops below 0' holds.
// But IC3IA may need '0 <= credit <= DEPTH' as a semantic lemma.

module credit_counter (
    input clk, input reset,
    input send_req, input recv_req, input flush,
    output bad
);
  localparam DEPTH = 4'd7;
  localparam IDLE = 2'd0, ACTIVE = 2'd1, HOLD = 2'd2;

  reg [1:0] mode;
  reg [3:0] credit;
  reg [3:0] used_reg;
  reg stall;
  reg [1:0] phase_reg;

  always @(posedge clk) begin
    if (reset) begin
      mode     <= IDLE;
      credit   <= DEPTH;
      used_reg <= 4'd0;
      stall    <= 1'b0;
      phase_reg <= 2'd0;
    end else begin
      case (mode)
        IDLE: begin mode <= ACTIVE; stall <= 1'b0; end
        ACTIVE: begin
          if (!stall) begin
            if (send_req && credit > 0) begin
              credit <= credit - 4'd1;
              used_reg <= used_reg + 4'd1;
              stall <= 1'b1;
              phase_reg <= phase_reg + 2'd1;
            end else if (recv_req && credit < DEPTH) begin
              credit <= credit + 4'd1;
              used_reg <= used_reg - 4'd1;
              stall <= 1'b1;
            end else if (flush) begin
              credit <= DEPTH;
              used_reg <= 4'd0;
              mode <= HOLD;
              phase_reg <= 2'd0;
            end
          end else begin
            stall <= 1'b0;
          end
        end
        HOLD: begin mode <= ACTIVE; end
      endcase
    end
  end

  // Property: credit overflow protection
  // credit should never exceed DEPTH.
  // Proving this requires the semantic lemma 'credit <= DEPTH'.
  // IC3IA may struggle without this invariant.
  assign bad = (credit > DEPTH);

endmodule
