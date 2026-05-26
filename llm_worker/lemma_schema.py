"""Lemma schema definitions and syntax-level validation for template-guided generation.

Eight allowed schema families. LLM must produce candidates from these only.
"""

from dataclasses import dataclass
from typing import List, Optional, Set

LEMMA_SCHEMAS = {
    "range": {
        "template": "{lo} <= {var} <= {hi}",
        "fields": ["var", "lo", "hi"],
        "description": "Variable bounded by constant range",
        "is_predicate": True,
    },
    "equality": {
        "template": "{lhs} = {rhs}",
        "fields": ["lhs", "rhs"],
        "description": "Two variables or expressions are equal",
        "is_predicate": True,
    },
    "disequality": {
        "template": "{lhs} != {rhs}",
        "fields": ["lhs", "rhs"],
        "description": "Two variables or expressions differ",
        "is_predicate": True,
    },
    "offset": {
        "template": "{lhs} = {rhs} + {offset}",
        "fields": ["lhs", "rhs", "offset"],
        "description": "One variable equals another plus constant offset",
        "is_predicate": True,
    },
    "bitslice": {
        "template": "{var}[{hi}:{lo}] = {value}",
        "fields": ["var", "hi", "lo", "value"],
        "description": "Bit-slice of a variable equals a constant",
        "is_predicate": True,
    },
    "mutual_exclusion": {
        "template": "!({a} && {b})",
        "fields": ["a", "b"],
        "description": "Two conditions cannot be simultaneously true",
        "is_predicate": True,
    },
    "mode_implication": {
        "template": "({mode} = {value}) => {constraint}",
        "fields": ["mode", "value", "constraint"],
        "description": "A mode/state value implies a constraint holds",
        "is_predicate": True,
    },
    "guarded_implication": {
        "template": "{guard} => {consequent}",
        "fields": ["guard", "consequent"],
        "description": "A guard condition implies a consequent relation",
        "is_predicate": True,
    },
}


FORBIDDEN_KEYWORDS: Set[str] = {
    "forall", "exists", "select", "store", "Array", "next(",
}


def get_schema_names() -> List[str]:
    """List of allowed schema names for LLM prompt."""
    return sorted(LEMMA_SCHEMAS.keys())


def get_schema_list_for_prompt() -> str:
    """Generate human-readable schema list for the LLM prompt."""
    lines = []
    for name in sorted(LEMMA_SCHEMAS.keys()):
        info = LEMMA_SCHEMAS[name]
        lines.append(f"{name}: {info['template']}  — {info['description']}")
    return "\n".join(lines)


def validate_lemma_syntax(lemma: str) -> bool:
    """Check lemma doesn't use forbidden constructs."""
    for kw in FORBIDDEN_KEYWORDS:
        if kw in lemma:
            return False
    return True


def detect_cube_subset(
    candidate_lemma: str,
    cti_literals: List[dict],
) -> bool:
    """Heuristic: is the candidate just a subset of CTI cube literals?
    Returns True if the candidate is cube-subset-like (undesirable)."""
    # Extract simplified varnames from CTI literals
    cti_terms = set()
    for lit in cti_literals:
        vn = lit.get("varname", "")
        if vn:
            cti_terms.add(vn)
    
    # Simple heuristic: if the lemma string is entirely contained in
    # any CTI varname, or is a conjunction of CTI varnames
    lemma_clean = candidate_lemma.strip()
    
    # Check if lemma is a single CTI literal
    for t in cti_terms:
        if lemma_clean == t or lemma_clean == f"{t} = true" or lemma_clean == f"{t} = false":
            return True
        if lemma_clean in t:
            return True
    
    return False


def check_triviality(lemma: str) -> Optional[str]:
    """Return reason if lemma is trivial (tautology, identity, etc).
    Returns None if nontrivial."""
    lemma_clean = lemma.strip().lower()
    
    trivial_patterns = [
        ("bad = false", "target property negation"),
        ("bad != true", "target property negation"),
        ("x = x", "tautology: identity"),
        ("true", "tautology"),
        ("false", "contradiction"),
    ]
    
    for pattern, reason in trivial_patterns:
        if pattern in lemma_clean:
            return reason
    
    return None


def check_input_constraint(
    lemma: str,
    variables_used: List[str],
    design_state_vars: List[str] = None,
    design_input_vars: List[str] = None,
) -> Optional[str]:
    """Check if lemma constrains unconstrained primary inputs.
    
    Returns reason string if lemma is input-constrained, None if safe.
    """
    if not design_input_vars:
        return None
    
    input_vars_used = [v for v in variables_used if v in design_input_vars]
    
    if not input_vars_used:
        return None
    
    # Check if inputs appear in consequent (guarded implication: guard => consequent)
    # Simple heuristic: inputs on right side of => or in consequent position
    has_implication = "=>" in lemma
    if has_implication:
        # Everything after => should not contain input vars
        imp_idx = lemma.rfind("=>")
        consequent = lemma[imp_idx + 2:].strip()
        for iv in input_vars_used:
            if iv in consequent:
                return (
                    "input_constrained: lemma constrains primary input '{}' "
                    "in consequent — use state-only or guarded-state form".format(iv)
                )
    
    # For non-implication lemmas with input vars
    return (
        "input_constrained: lemma contains primary input(s) {} "
        "— consider guard-only position or state-only form".format(
            ", ".join(input_vars_used)
        )
    )
