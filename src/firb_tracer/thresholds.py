"""Statutory percentage thresholds, and one safe way to compare against them.

Every threshold in the regime is expressed as "at least" a percentage, so the
comparison is always >= (rules document, R2). Percentages are floats, and
floating-point arithmetic can turn an exact 20% into 19.999999999999996%, so
comparisons allow a tiny tolerance.
"""

SUBSTANTIAL = 20.0  # substantial interest, FATA s 4
AGGREGATE_SUBSTANTIAL = 40.0  # aggregate substantial interest, FATA s 4; FATR s 17(3)
DIRECT = 10.0  # direct interest, FATR s 16(a)
DIRECT_WITH_ARRANGEMENT = 5.0  # direct interest with a business arrangement, FATR s 16(b)
VETO_DEEMED = 20.0  # potential voting power deemed by FATA s 22(4)

_TOLERANCE = 1e-9


def meets(pct: float, threshold: float) -> bool:
    """True if pct is at least the threshold."""
    return pct >= threshold - _TOLERANCE
