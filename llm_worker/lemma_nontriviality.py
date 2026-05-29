#!/usr/bin/env python3
"""Nontriviality and usefulness gate for repaired lemmas.

Checks:
1. Bitwidth tautology — reject comparisons always true/false due to bitwidth
2. Impossible antecedent — antecedent unsatisfiable by bitwidth alone
3. Tautological consequent — consequent always true by bitwidth
4. Original CE blocking — repair must block the counterexample
5. Variable relevance — repair must use variables from original candidate

Verdict labels:
  solver_verified_useful       — passes all gates
  solver_verified_trivial       — passes solver, fails nontriviality
  counterexample_not_blocked    — solver-pass but doesn't exclude original CE
  nontriviality_unknown         — cannot determine
"""

import re
from typing import Dict, List, Optional, Tuple, Set


def parse_variables(lemma: str) -> List[str]:
    return sorted(set(re.findall(r'\b(state\d+)\b', lemma)))


def _get_bitwidth(var_name: str, bitwidths: Dict[str, int]) -> Optional[int]:
    return bitwidths.get(var_name)


def _max_val(bw: int) -> int:
    return (1 << bw) - 1


# --- S-expression parsing ---

def _parse_s_expr(s: str):
    """Parse a balanced S-expression. Returns (parsed, consumed)."""
    s = s.strip()
    if not s or s[0] != '(':
        return None, 0
    pos = 1
    result = []
    buf = ""
    while pos < len(s):
        ch = s[pos]
        if ch == '(':
            if buf.strip():
                result.append(buf.strip())
                buf = ""
            sub, consumed = _parse_s_expr(s[pos:])
            if sub is None:
                return None, 0
            result.append(sub)
            pos += consumed
        elif ch == ')':
            if buf.strip():
                result.append(buf.strip())
            return result, pos + 1
        elif ch == ' ':
            if buf.strip():
                result.append(buf.strip())
            buf = ""
            pos += 1
        else:
            buf += ch
            pos += 1
    return None, 0


def _format_expr(expr) -> str:
    if isinstance(expr, list):
        return '(' + ' '.join(_format_expr(e) for e in expr) + ')'
    return str(expr)


def _extract_implication_parts(lemma: str) -> Optional[Tuple[str, str]]:
    """Extract (antecedent_str, consequent_str) from (=> A B)."""
    parsed, _ = _parse_s_expr(lemma)
    if parsed and len(parsed) >= 3 and parsed[0] == '=>':
        ante = parsed[1]
        cons = parsed[2]
        ante_str = _format_expr(ante) if isinstance(ante, list) else ante
        cons_str = _format_expr(cons) if isinstance(cons, list) else cons
        return ante_str, cons_str
    return None


# --- Subexpression tautology check ---

def _check_subexpr_tautology(expr: str, bitwidths: Dict[str, int]) -> Optional[str]:
    """Check if a subexpression is a bitwidth tautology or contradiction."""
    expr = expr.strip()

    # (<= stateX N): upper bound — tautology if N >= 2^w - 1
    m = re.match(r'\(\s*<=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        bw = _get_bitwidth(var, bitwidths)
        if bw is not None and val >= _max_val(bw):
            return "tautology"

    # (>= stateX N): lower bound — tautology if N <= 0
    m = re.match(r'\(\s*>=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        if val <= 0:
            return "tautology"

    # (< stateX N): strict upper bound — tautology if N > 2^w - 1
    m = re.match(r'\(\s*<\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        bw = _get_bitwidth(var, bitwidths)
        if bw is not None and val > _max_val(bw):
            return "tautology"

    # (not (= stateX N)): tautology if N > 2^w - 1 (can never equal)
    m = re.match(r'\(\s*not\s*\(\s*=\s*(state\d+)\s+(\d+)\s*\)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        bw = _get_bitwidth(var, bitwidths)
        if bw is not None and val > _max_val(bw):
            return "tautology"

    # (= stateX N): contradiction if N > 2^w - 1 (impossible value)
    m = re.match(r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        bw = _get_bitwidth(var, bitwidths)
        if bw is not None and val > _max_val(bw):
            return "contradiction"

    return None


# --- Check 1: Bitwidth tautology (whole lemma) ---

def check_bitwidth_tautology(lemma: str, bitwidths: Dict[str, int]) -> Optional[str]:
    """Check if lemma is always true/false due to bitwidth constraints."""
    lemma_clean = lemma.strip()

    # Standalone comparisons
    taut = _check_subexpr_tautology(lemma_clean, bitwidths)
    if taut:
        return taut

    # Implication: check consequent for tautology, antecedent for impossibility
    parts = _extract_implication_parts(lemma_clean)
    if parts:
        ante_str, con_str = parts

        con_taut = _check_subexpr_tautology(con_str, bitwidths)
        if con_taut == "tautology":
            return "tautology"

        ante_contra = _check_subexpr_tautology(ante_str, bitwidths)
        if ante_contra == "contradiction":
            return "tautology"

        # Implicit: (= stateX N) where N > 2^w - 1 → impossible antecedent
        m_eq = re.match(r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)', ante_str)
        if m_eq:
            var, val = m_eq.group(1), int(m_eq.group(2))
            bw = _get_bitwidth(var, bitwidths)
            if bw is not None and val > _max_val(bw):
                return "tautology"

    return None


# --- Check 2: Impossible antecedent ---

def check_impossible_antecedent(lemma: str, bitwidths: Dict[str, int]) -> Optional[str]:
    """Check if antecedent is impossible by bitwidth."""
    parts = _extract_implication_parts(lemma.strip())
    if not parts:
        return None
    ante_str, _ = parts

    m_eq = re.match(r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)', ante_str)
    if m_eq:
        var, val = m_eq.group(1), int(m_eq.group(2))
        bw = _get_bitwidth(var, bitwidths)
        if bw is not None and val > _max_val(bw):
            return "impossible"
    return None


# --- Check 3: Tautological consequent ---

def check_tautological_consequent(lemma: str, bitwidths: Dict[str, int]) -> Optional[str]:
    """Check if consequent is always true by bitwidth."""
    parts = _extract_implication_parts(lemma.strip())
    if not parts:
        return None
    _, con_str = parts
    return _check_subexpr_tautology(con_str, bitwidths)


# --- Check 4: Original CE blocking ---

def check_ce_blocking(lemma: str, bitwidths: Dict[str, int],
                      original_ce: Dict) -> Optional[str]:
    """Check if the original counterexample still violates the repaired lemma.

    A good repair should make the original CE NOT a violation.
    Returns "ce_not_blocked" if the repaired lemma is still violated by the CE,
    or "ce_blocked" if the original CE no longer violates the lemma.
    """
    if not original_ce:
        return None

    next_values = original_ce.get("next_values", {})
    if not next_values:
        return None

    lemma_clean = lemma.strip()
    violated = False

    def _ce_val(var_name):
        nk = var_name + "_next"
        v = next_values.get(nk)
        return int(v) if v is not None else None

    # --- Implication: A => B ---
    # Violated when A holds AND B fails
    parts = _extract_implication_parts(lemma_clean)
    if parts:
        ante_str, con_str = parts

        # Check if antecedent holds on CE
        ante_holds = _expr_holds_on_ce(ante_str, next_values)
        con_holds = _expr_holds_on_ce(con_str, next_values)

        if ante_holds and not con_holds:
            violated = True

    # --- Mutual exclusion: !(A and B) ---
    # Violated when both A and B hold
    mutex_match = re.match(
        r'\(\s*!\s*\(\s*and\s*\(=\s*(state\d+)\s+(\d+)\s*\)\s*\(=\s*(state\d+)\s+(\d+)\s*\)\s*\)\s*\)',
        lemma_clean)
    if mutex_match:
        v1, val1 = mutex_match.group(1), int(mutex_match.group(2))
        v2, val2 = mutex_match.group(3), int(mutex_match.group(4))
        n1, n2 = _ce_val(v1), _ce_val(v2)
        if n1 == val1 and n2 == val2:
            violated = True

    if violated:
        return "ce_not_blocked"
    return "ce_blocked"


def _expr_holds_on_ce(expr: str, next_values: Dict[str, str]) -> bool:
    """Check if an S-expression holds on the given next-state assignment."""
    expr = expr.strip()

    # (= stateX V)
    m = re.match(r'\(\s*=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        ce = next_values.get(var + "_next")
        return ce is not None and int(ce) == val

    # (<= stateX V)
    m = re.match(r'\(\s*<=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        ce = next_values.get(var + "_next")
        return ce is not None and int(ce) <= val

    # (>= stateX V)
    m = re.match(r'\(\s*>=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        ce = next_values.get(var + "_next")
        return ce is not None and int(ce) >= val

    # (< stateX V)
    m = re.match(r'\(\s*<\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        var, val = m.group(1), int(m.group(2))
        ce = next_values.get(var + "_next")
        return ce is not None and int(ce) < val

    # (not P)
    m = re.match(r'\(\s*not\s+(.+)\s*\)', expr)
    if m:
        return not _expr_holds_on_ce(m.group(1), next_values)

    # Unknown pattern — conservatively assume holds
    return True


# --- Check 5: Variable relevance ---

def check_variable_relevance(repair_vars: List[str],
                             original_vars: List[str],
                             original_ce: Optional[Dict] = None) -> Optional[str]:
    """Check if repair uses variables from original candidate or CE context."""
    orig_set = set(original_vars)
    if original_ce:
        for k in list(original_ce.get("next_values", {}).keys()):
            m = re.match(r'(state\d+)_next', k)
            if m:
                orig_set.add(m.group(1))

    repair_set = set(repair_vars)
    if not repair_set:
        return "no_variables"
    if repair_set <= orig_set:
        return None
    unrelated = repair_set - orig_set
    if unrelated:
        return f"unrelated: {', '.join(sorted(unrelated))}"
    return None


# --- Main gate function ---

def gate_repaired_lemma(lemma: str,
                        bitwidths: Dict[str, int],
                        original_vars: List[str],
                        original_ce: Optional[Dict] = None,
                        solver_verdict: str = "") -> Dict:
    """Apply all nontriviality checks to a repaired lemma."""
    repair_vars = parse_variables(lemma)

    result = {
        "lemma": lemma[:150],
        "solver_verdict": solver_verdict,
        "checks": {},
        "gate_verdict": "nontriviality_unknown",
        "issues": [],
    }

    bt = check_bitwidth_tautology(lemma, bitwidths)
    result["checks"]["bitwidth_tautology"] = bt or "nontrivial"
    if bt:
        result["issues"].append(f"bitwidth_{bt}")

    imp = check_impossible_antecedent(lemma, bitwidths)
    result["checks"]["impossible_antecedent"] = imp or "feasible"
    if imp:
        result["issues"].append("impossible_antecedent")

    tc = check_tautological_consequent(lemma, bitwidths)
    result["checks"]["tautological_consequent"] = tc or "nontrivial"
    if tc:
        result["issues"].append("tautological_consequent")

    if original_ce:
        ce_block = check_ce_blocking(lemma, bitwidths, original_ce)
        result["checks"]["ce_blocking"] = ce_block or "unknown"
        if ce_block == "ce_not_blocked":
            result["issues"].append("counterexample_not_blocked")
    else:
        result["checks"]["ce_blocking"] = "no_ce_data"

    vr = check_variable_relevance(repair_vars, original_vars, original_ce)
    result["checks"]["variable_relevance"] = vr or "ok"
    if vr:
        result["issues"].append(vr)

    is_solver_pass = solver_verdict in ("solver_verified_strong", "solver_inductive")

    if not is_solver_pass:
        result["gate_verdict"] = solver_verdict or "solver_rejected"
    elif bt == "tautology" or bt == "contradiction":
        result["gate_verdict"] = "solver_verified_trivial"
    elif tc == "tautology":
        result["gate_verdict"] = "solver_verified_trivial"
    elif imp == "impossible":
        result["gate_verdict"] = "solver_verified_trivial"
    elif "counterexample_not_blocked" in result["issues"]:
        result["gate_verdict"] = "counterexample_not_blocked"
    elif result["issues"]:
        result["gate_verdict"] = "solver_verified_trivial"
    else:
        result["gate_verdict"] = "solver_verified_useful"

    return result
