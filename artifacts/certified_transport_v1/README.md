# Gate 5A0 — Certified Transport Population Census

Decision: **STOP (`population-insufficient`)**.

The frozen census found 11 certified safe bases and six T1-applicable bases,
below the preregistered requirements of 12 and eight. The remaining conditions
passed: 11 independent source families, all required invariant classes, 11
T2-applicable bases, 11 T3-applicable bases, ten input-driven T3 families, and
four unsafe controls.

Eight baseline-interpolation invariant-recovery attempts were rejected as
`show-invar-runtime-incompatible`. The installed `build/pono` is linked against
`libasan.so.6`, and AddressSanitizer cannot reserve its shadow mapping under the
inherited 60,000,000 KiB hard virtual-memory limit. No alternate binary, release
rebuild, solver, population padding, or silent fallback was used.

Per the frozen Gate 5A0 rule, no transformed BTOR2 variant, map, transport
utility run, or LLM call was produced. `population.json` is the self-hashed
canonical decision; `source_certificates/` contains the 11 independently
rechecked C1/C2/C3 source proofs.

Canonical command:

```bash
SVCOMP_BTOR_REPO=/tmp/svcomp25-transport-clean \
HWMCC_ROOT=/home/swear01/hwmcc_benchmarks \
python3 scripts/build_transport_population.py \
  --phase1-summary artifacts/phase1_2_summary_v1.json \
  --representation-summary artifacts/representation_phase_v1/summary.json \
  --out artifacts/certified_transport_v1/population.json
```

Population SHA-256:

```text
3de42161c17a90bf12e2639f1d8d15a676d7fbbfe2c747efd0966e670a659e7b
```
