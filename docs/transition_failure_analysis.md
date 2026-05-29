# Transition Failure Analysis

Generated from counterexample models + transition slices.

## Summary

| Candidate | Failure | CE Values | Transition Root Cause | Recommendation |
|---|---|---|---|---|
| C1: state1536=10=>state790=0 | one_step_fail | 1536=10, 790=1 | No causal link between mode and stall | reject |
| rsyn_001: state1536=15=>state2002=1 | one_step_fail | 1536=15, 2002=1 | Shared deps but 1536=15 reachable without 2002=1 | need stronger guard |
| rsyn_002: !(state1536=15&&state2002=0) | one_step_fail | 1536=15, 2002=1 | CE doesn't show violation but other transitions do | reject |

(Full analysis in JSON at `logs/formal_yield/transition_failure_analysis.json`)
