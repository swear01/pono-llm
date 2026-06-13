# Archive — Retired Plans

These plans described the **reactive per-CTI blocking clause** approach (Q2–Q4).
All reached 0% accept rate. Root causes:

1. Wrong abstraction level: LLM picking bit-level literals from `stateNN` stats
2. Semantic inversion in prompts (`clause_false_at_init` when C++ needs TRUE)
3. SAME-column impossibility: 93% of digest refs have init=CTI, negation fails by construction
4. Fundamental mismatch: LLM asked to be a SAT proxy, which it is not

**Do not resume these plans.** See `docs/plans/semantic_invariant_injection_v1_plan.md` for the new direction.

## Files

| File | Why archived |
|------|-------------|
| clause_quality_q2_plan.md | Q2: 0% accept, no init info |
| clause_quality_q3_plan.md | Q3: 0% accept, digest-neg shape ~95% but all SAME-column |
| clause_quality_q3_1_q3_2_plan.md | Q3 sub-plans, same outcome |
| clause_quality_q3_postmortem_plan.md | Postmortem of Q3; correct diagnosis but wrong fix |
| clause_quality_q4_harness_plan.md | Q4: 0% accept even with init_raw; prompt semantics inverted |
| frame_snapshot_quality_plan.md | Track B: prompt patches on wrong paradigm |
| batch-cti-single-conclusion-plan.md | Still reactive per-CTI |
| phase_a_postmortem_plan.md | Old postmortem |
