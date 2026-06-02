#!/usr/bin/env python3
"""WP2-3: Generalization DSL v2 — schema-based candidate output.

LLM outputs structured schema + slots.
Harness deterministically lowers to supported SMT.
"""

import json, os, sys, re


SUPPORTED_SCHEMAS = [
    "single_guard_implication",
    "guarded_implication_2",
    "guarded_implication_3",
    "nary_mutex_3",
    "or_consequent_guard",
    "reject",
]


def validate_variable(var_name):
    return bool(re.match(r'^state\d+$', var_name))


def validate_value(val_str):
    return val_str in ("0", "1")


def validate_slot(slot):
    if not isinstance(slot, dict): return False, "not a dict"
    v = slot.get("var", "")
    val = slot.get("value", "")
    if not validate_variable(v): return False, f"invalid var: {v}"
    if not validate_value(val): return False, f"invalid value: {val}"
    return True, ""


def validate_dsl_candidate(candidate):
    """Validate a DSL candidate and return (is_valid, reason, lowered_smt)."""
    # Required metadata
    if not candidate.get("source_artifact_id"):
        return False, "missing source_artifact_id", "", None
    if not candidate.get("generalization_operator"):
        return False, "missing generalization_operator", "", None

    schema = candidate.get("schema", "")
    if schema not in SUPPORTED_SCHEMAS:
        return False, f"unsupported schema: {schema}", "", None

    if schema == "reject":
        return True, "reject", "", {"schema": "reject", "reason": candidate.get("reason", "")}

    # Schema-specific validation
    try:
        if schema == "single_guard_implication":
            ok, reason = validate_slot(candidate.get("guard", {}))
            if not ok: return False, reason, "", None
            ok, reason = validate_slot(candidate.get("consequent", {}))
            if not ok: return False, reason, "", None
            g = candidate["guard"]
            c = candidate["consequent"]
            if g["var"] == c["var"]:
                return False, "guard and consequent same variable", "", None
            smt = f"(=> (= {g['var']} #b{g['value']}) (= {c['var']} #b{c['value']}))"
            return True, "", smt, [g["var"], c["var"]]

        elif schema == "guarded_implication_2":
            guards = candidate.get("guards", [])
            if len(guards) != 2:
                return False, f"need exactly 2 guards, got {len(guards)}", "", None
            for g in guards:
                ok, reason = validate_slot(g)
                if not ok: return False, reason, "", None
            ok, reason = validate_slot(candidate.get("consequent", {}))
            if not ok: return False, reason, "", None
            c = candidate["consequent"]
            all_vars = [g["var"] for g in guards] + [c["var"]]
            if len(set(all_vars)) < len(all_vars):
                return False, "duplicate variable in guards/consequent", "", None
            gs = " ".join(f"(= {g['var']} #b{g['value']})" for g in guards)
            smt = f"(=> (and {gs}) (= {c['var']} #b{c['value']}))"
            return True, "", smt, all_vars

        elif schema == "guarded_implication_3":
            guards = candidate.get("guards", [])
            if len(guards) != 3:
                return False, f"need exactly 3 guards, got {len(guards)}", "", None
            for g in guards:
                ok, reason = validate_slot(g)
                if not ok: return False, reason, "", None
            ok, reason = validate_slot(candidate.get("consequent", {}))
            if not ok: return False, reason, "", None
            c = candidate["consequent"]
            all_vars = [g["var"] for g in guards] + [c["var"]]
            if len(set(all_vars)) < len(all_vars):
                return False, "duplicate variable", "", None
            gs = " ".join(f"(= {g['var']} #b{g['value']})" for g in guards)
            smt = f"(=> (and {gs}) (= {c['var']} #b{c['value']}))"
            return True, "", smt, all_vars

        elif schema == "nary_mutex_3":
            lits = candidate.get("literals", [])
            if len(lits) != 3:
                return False, f"nary_mutex_3 needs exactly 3 literals", "", None
            for lit in lits:
                ok, reason = validate_slot(lit)
                if not ok: return False, reason, "", None
            vars_found = [l["var"] for l in lits]
            if len(set(vars_found)) < len(vars_found):
                return False, "duplicate variable in mutex", "", None
            eqs = " ".join(f"(= {l['var']} #b{l['value']})" for l in lits)
            smt = f"(not (and {eqs}))"
            return True, "", smt, vars_found

        elif schema == "or_consequent_guard":
            ok, reason = validate_slot(candidate.get("guard", {}))
            if not ok: return False, reason, "", None
            g = candidate["guard"]
            cs = candidate.get("consequents", [])
            if len(cs) != 2:
                return False, f"need exactly 2 consequents", "", None
            for c in cs:
                ok, reason = validate_slot(c)
                if not ok: return False, reason, "", None
            all_vars = [g["var"]] + [c["var"] for c in cs]
            if len(set(all_vars)) < len(all_vars):
                return False, "duplicate variable", "", None
            cs_str = " ".join(f"(= {c['var']} #b{c['value']})" for c in cs)
            smt = f"(=> (= {g['var']} #b{g['value']}) (or {cs_str}))"
            return True, "", smt, all_vars

    except KeyError as e:
        return False, f"missing required field: {e}", "", None

    return False, "unknown schema", "", None


def canonicalize_dsl(candidate):
    """Return a canonical version for dedup."""
    d = dict(candidate)
    d.pop("candidate_id", None)
    d.pop("_source_file", None)
    return json.dumps(d, sort_keys=True)


def main():
    # Self-test
    tests = [
        ("valid single_guard", {
            "schema": "single_guard_implication",
            "guard": {"var": "state469", "value": "0"},
            "consequent": {"var": "state15", "value": "0"},
            "source_artifact_id": "a1",
            "generalization_operator": "clause_lifting",
        }),
        ("valid guarded_2", {
            "schema": "guarded_implication_2",
            "guards": [{"var": "state469", "value": "0"}, {"var": "state471", "value": "0"}],
            "consequent": {"var": "state15", "value": "0"},
            "source_artifact_id": "a1",
            "generalization_operator": "clause_lifting",
        }),
        ("invalid duplicate vars", {
            "schema": "guarded_implication_2",
            "guards": [{"var": "state469", "value": "0"}, {"var": "state469", "value": "0"}],
            "consequent": {"var": "state15", "value": "0"},
            "source_artifact_id": "a1",
            "generalization_operator": "clause_lifting",
        }),
        ("invalid schema", {"schema": "unsupported", "source_artifact_id": "a1",
                             "generalization_operator": "x"}),
        ("missing metadata", {"schema": "single_guard_implication",
                              "guard": {"var": "stateX", "value": "0"},
                              "consequent": {"var": "stateY", "value": "0"}}),
    ]
    for name, c in tests:
        ok, reason, smt, _ = validate_dsl_candidate(c)
        status = "PASS" if "invalid" in name and not ok else ("PASS" if ok else "FAIL" if "valid" in name else "OK")
        print(f"{status:4s} {name:30s} {reason[:60]}, smt={smt[:60] if smt else 'N/A'}")

    out = "logs/formal_yield"
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "generalization_dsl_selftest.json"), "w") as f:
        json.dump({"schemas": SUPPORTED_SCHEMAS, "tests_ran": len(tests)}, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
