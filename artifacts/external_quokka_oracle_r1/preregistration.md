# External Oracle Replication R1 preregistration

This is an append-only successor to the preserved Ledger v1 decision
`STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE`. New public evidence at Quokka commit
`60301cb79ba594945f2049990421f5d5d4d95afc` authorizes a new prospective event;
it does not overwrite the earlier decision or reopen any internal STOP.

The study applies G1--G5 to ground-truth invariants using UAutomizer. It makes
no LLM calls and changes neither Quokka nor a verifier algorithm. The three
arms are Q0 original, Q1 assertion with the final property assertion removed,
and Q2 assumption with the original property retained. Raw arm results are
authoritative; no aggregate fallback is allowed.

## Qualification and resources

Qualification requires at least 50 GT programs, at least 95% valid insertion
entries, parseable program/property/invariant/line records, a pinned runnable
UAutomizer, and a recursive input manifest. The smoke population is the first
25 eligible invariant entries sorted by `(program_sha256, task_id)`, frozen
before verifier execution.

Each invocation receives one CPU core, 15 GiB address-space limit, and 600
seconds. Q0, Q1, and Q2 use the same binary, property, ordering, and host.
Results retain transformed source, stdout/stderr, exit code, verdict, wall and
CPU time, peak memory, and hashes. Oracle cost is reported as both
`max(Q1,Q2)` and `Q1+Q2`.

Smoke GO requires transformation success >=95%, zero wrong or property
mismatch, zero fallback, at least 20/25 raw-classifiable tasks, and >=90%
classification agreement across two clean generated-source executions. Only a
GO authorizes the full eligible population.

Primary classes are `G1_REPRESENTATION_FAILURE`, `G2_INVALID_INVARIANT`,
`G3_CONSUMER_NO_CAPACITY`, `G4_PROPERTY_INSUFFICIENT`,
`G5_NEGATIVE_RUNTIME_UTILITY`, `PASS`, and `INFRASTRUCTURE_FAILURE`. Q1 not TRUE
is G2. Q1 TRUE with Q2 not TRUE remains G3/G4 unresolved unless independent
consumer-acceptance evidence separates them. Any unexpected FALSE,
disagreement, or property mismatch is infrastructure failure.

Full GO requires >=50 eligible tasks, >=4 structural families, zero wrong, at
least 10 PASS, at least 10 post-G2 failures or 10% of eligible tasks, >=90%
classification stability on a three-run subset, hashes for every input,
transformation, and result, and clean-checkout reconstruction. Failure of any
hard condition stops R1 and does not authorize a fourth corpus.
