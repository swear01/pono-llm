# External Oracle Replication R1 smoke report

## Decision: STOP

The frozen 25-entry smoke ran Q0 original, Q1 assert, and Q2 assume twice, for
150 raw UAutomizer invocations. No LLM was called and no aggregate fallback was
used. Transformation succeeded for all tasks, no FALSE verdict or property
mismatch occurred, and 24/25 tasks had classifiable raw results.

The hard stability threshold failed: only 18/25 primary classifications agreed
between trials (72%, required 90%). Seven tasks flipped only between `PASS` and
`G5_NEGATIVE_RUNTIME_UTILITY`, showing that a single strict wall-time comparison
is not stable enough on this smoke. Trial counts were 10 PASS / 14 G5 / 1
infrastructure and 11 PASS / 13 G5 / 1 infrastructure.

One task, `geo2-ll_unwindbound5_2.c`, reproducibly produced UAutomizer exit 7
for both transformed arms because the frontend could not represent the C
constant `18446744073709551615`. It is fail-closed as
`INFRASTRUCTURE_FAILURE`, not semantic evidence about its invariant.

The trials regenerated and hash-checked transformed sources in the same pinned
checkout. They did not satisfy the stricter two-clean-checkout condition. Since
the stability condition already failed, no third execution or full-population
run is authorized. Per preregistration, R1 stops here and no fourth corpus may
be selected.

The runner initially stored a provisional classification that treated ERROR as
G2. The final summary ignores that derived field and reclassifies exclusively
from immutable raw verdicts, exit codes, and logs; ERROR is infrastructure.
This correction does not change any verifier output or threshold.
