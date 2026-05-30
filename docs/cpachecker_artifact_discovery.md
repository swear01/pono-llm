# CPAchecker Artifact Discovery

## Search Result

No CPAchecker artifacts found in this repository (`pono-llm`).

Search terms: `context_unlock`, `B5-MR`, `b5_mr`, `CPAchecker`, `candidate_fates`,
`bootstrap`, `refinements`, `interpolants`, `spurious` — no matching files.

## Missing Artifacts

The CPAchecker context-unlock work is in a **separate repository**. The
`pono-llm` repo contains only the Pono/IC3IA thread. CPAchecker artifacts
(CEGAR traces, context dumps, B5-MR candidate fates) are in the CPAchecker
fork or a separate integration repo.

## External Repo/Path Needed

The commit `a9df4331` referenced in the context-unlock docs is likely from
a different repository. To implement B5-MR candidate fate logging, the
CPAchecker fork with bootstrap integration needs to be identified and
accessed.

## Next Action

1. Identify CPAchecker fork with bootstrap integration.
2. Locate B5-MR code path (repair candidate generation → parse → validate → inject).
3. Add per-candidate JSONL logging following the schema in `docs/b5_mr_candidate_fate_schema.md`.
4. Re-run context-unlocked benchmark with logging enabled.
5. Classify failures from the candidate fate log.
