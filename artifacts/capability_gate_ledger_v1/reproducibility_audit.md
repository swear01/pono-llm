# Reproducibility audit

## Result

The ledger is reproducible on the audited two-checkout environment and rejects
changed evidence bytes. Seven rows point to tracked evidence with commit-bound
chronology. One CPAchecker runtime-utility row points to an untracked result;
it is explicitly classified `working-tree-only`, so a clean checkout alone
cannot reconstruct the complete eight-row ledger.

The ledger covers two verifier ecosystems, three artifact classes, five
distinct stages (G0, G1, G2, G3, G5), positive controls, and four different
root-cause classes. It does not claim complete G0--G6 coverage. In particular,
the Pono routing result informs LLM marginality but remains grouped with its
original representation study rather than being relabeled post hoc as a new
preregistered G6 experiment.

## Prospective decision

The Quokka/InvBench paper and partial public derivatives were discoverable,
but the paper's anonymous release endpoint returned HTTP 401 and the inspected
public derivative did not expose exact candidate predicates and insertion
locations. The train-row metadata endpoint returned HTTP 503 during the
census. Because the frozen contract requires all fields in one reconstructible
release, the prospective decision is
`STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE`. No alternate corpus was selected.

## Decision savings

The recorded early decisions avoided reopening invalid-route repair and paid
capture, implementing a new modular proof kernel for the v2 population,
building a proof graph for initially false candidates, and implementing a
transport mapper without a sufficient population. These are avoided actions,
not measured engineering-hour savings.
