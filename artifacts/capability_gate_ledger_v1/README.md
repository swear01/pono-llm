# Capability Gate Ledger v1

This bundle is the canonical Oracle-First Capability Audit index generated
from `scripts/capability_gate_catalog_v1.json`.

- `ledger.json`: eight hash-checked studies spanning CPAchecker and Pono.
- `external_replication.json`: preregistered Quokka/InvBench public-artifact
  census and `STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE` decision.
- `reproducibility_audit.md`: scope and limitations of reconstruction.
- `integrity.json`: file SHA-256 manifest.

Rebuild and validate from the repository root:

```sh
python3 scripts/build_capability_gate_ledger.py
python3 scripts/validate_capability_gate_ledger.py
```

The CPAchecker shadow-utility row deliberately remains
`working-tree-only`. Its exact result bytes are hashed, but it is not evidence
of clean-checkout reproducibility. The builder fails rather than silently
dropping that row if those bytes are absent or changed.
