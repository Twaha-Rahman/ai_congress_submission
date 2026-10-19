"""Allowed value sets for supported rule kinds.

Requirement rules describe the set of compliant actions:

* ``required_minimum``  -> ``{x : x >= value}``
* ``maximum_allowed``   -> ``{x : x <= value}``
* ``exactly_required``  -> ``{x : x == value}``

``advised_sufficient`` and ``operating_exact`` describe an advised or planned
*action value*, not a requirement set.  Different numbers alone never establish a
conflict: two requirements are only compared through the intersection of their
allowed sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from math import ceil, floor

from ..contracts.common import Rule, RuleKind, UnitKind

REQUIREMENT_KINDS = frozenset(
    {RuleKind.REQUIRED_MINIMUM, RuleKind.MAXIMUM_ALLOWED, RuleKind.EXACTLY_REQUIRED}
)
ADVICE_KINDS = frozenset({RuleKind.ADVISED_SUFFICIENT})
OPERATING_KINDS = frozenset({RuleKind.OPERATING_EXACT})


class Domain(str, Enum):
    INTEGER = "integer"
    DECIMAL = "decimal"


@dataclass(frozen=True)
class Constraint:
    """Interval of allowed values; ``None`` bounds are unbounded."""

    lo: Decimal | None
    lo_inclusive: bool
    hi: Decimal | None
    hi_inclusive: bool


def domain_for(unit: UnitKind) -> Domain:
    return Domain.INTEGER if unit is UnitKind.APPROVALS else Domain.DECIMAL


def constraint_for(rule: Rule) -> Constraint:
    value = rule.decimal_value()
    if rule.kind is RuleKind.REQUIRED_MINIMUM:
        return Constraint(value, True, None, False)
    if rule.kind is RuleKind.MAXIMUM_ALLOWED:
        return Constraint(None, False, value, True)
    if rule.kind is RuleKind.EXACTLY_REQUIRED:
        return Constraint(value, True, value, True)
    if rule.kind in (RuleKind.ADVISED_SUFFICIENT, RuleKind.OPERATING_EXACT):
        return Constraint(value, True, value, True)
    raise ValueError(f"unsupported rule kind: {rule.kind}")  # pragma: no cover


def _stricter_lower(a: Constraint, b: Constraint) -> tuple[Decimal | None, bool]:
    if a.lo is None:
        return b.lo, b.lo_inclusive
    if b.lo is None:
        return a.lo, a.lo_inclusive
    if a.lo > b.lo:
        return a.lo, a.lo_inclusive
    if b.lo > a.lo:
        return b.lo, b.lo_inclusive
    return a.lo, a.lo_inclusive and b.lo_inclusive


def _stricter_upper(a: Constraint, b: Constraint) -> tuple[Decimal | None, bool]:
    if a.hi is None:
        return b.hi, b.hi_inclusive
    if b.hi is None:
        return a.hi, a.hi_inclusive
    if a.hi < b.hi:
        return a.hi, a.hi_inclusive
    if b.hi < a.hi:
        return b.hi, b.hi_inclusive
    return a.hi, a.hi_inclusive and b.hi_inclusive


def _lowest_allowed(constraint: Constraint, domain: Domain) -> Decimal | None:
    if constraint.lo is None:
        return None
    if constraint.lo_inclusive:
        return constraint.lo
    if domain is Domain.INTEGER:
        return Decimal(floor(constraint.lo) + 1)
    return constraint.lo


def _highest_allowed(constraint: Constraint, domain: Domain) -> Decimal | None:
    if constraint.hi is None:
        return None
    if constraint.hi_inclusive:
        return constraint.hi
    if domain is Domain.INTEGER:
        return Decimal(ceil(constraint.hi) - 1)
    return constraint.hi


def intersect(a: Constraint, b: Constraint, domain: Domain) -> Constraint | None:
    """Intersection of two allowed sets, or ``None`` when empty."""

    lo, lo_inclusive = _stricter_lower(a, b)
    hi, hi_inclusive = _stricter_upper(a, b)
    if lo is not None and hi is not None:
        if lo > hi:
            return None
        if lo == hi and not (lo_inclusive and hi_inclusive):
            return None
    candidate = Constraint(lo, lo_inclusive, hi, hi_inclusive)
    if domain is Domain.INTEGER:
        lowest = _lowest_allowed(candidate, domain)
        highest = _highest_allowed(candidate, domain)
        if lowest is not None and highest is not None and lowest > highest:
            return None
        if lowest is None and highest is None:
            return None  # pragma: no cover - defensive
        if highest is not None and highest < 0:
            return None
        if lowest is not None and lowest > 0 and highest is not None and highest < lowest:
            return None  # pragma: no cover - defensive
    return candidate


def contains(constraint: Constraint, value: Decimal, domain: Domain) -> bool:
    if constraint.lo is not None:
        if value < constraint.lo:
            return False
        if value == constraint.lo and not constraint.lo_inclusive:
            return False
    if constraint.hi is not None:
        if value > constraint.hi:
            return False
        if value == constraint.hi and not constraint.hi_inclusive:
            return False
    if domain is Domain.INTEGER and value != value.to_integral_value():
        return False
    return True


def witness_value(constraint: Constraint, domain: Domain) -> Decimal | None:
    """A concrete value that satisfies the constraint (used in explanations)."""

    lowest = _lowest_allowed(constraint, domain)
    if lowest is not None:
        return lowest
    highest = _highest_allowed(constraint, domain)
    if highest is not None:
        if domain is Domain.INTEGER and highest < 0:
            return None
        return highest
    return None


def is_empty(constraint: Constraint | None, domain: Domain) -> bool:
    if constraint is None:
        return True
    if domain is Domain.INTEGER:
        lowest = _lowest_allowed(constraint, domain)
        highest = _highest_allowed(constraint, domain)
        if lowest is not None and highest is not None and lowest > highest:
            return True
        if highest is not None and highest < 1 and lowest is not None:
            return True
    return False


def _format_value(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def describe_violation(value: Decimal, constraint: Constraint, unit: UnitKind) -> str:
    """Explicit inequality showing why ``value`` is outside the allowed set.

    The comparison direction is always taken from the actual constraint, so an
    operating value above a maximum renders ``value > bound`` rather than a
    misleading less-than comparison.
    """

    if constraint.lo is not None:
        below_lo = value < constraint.lo or (
            value == constraint.lo and not constraint.lo_inclusive
        )
        if below_lo:
            return f"{_format_value(value)} < {_format_value(constraint.lo)}"
    if constraint.hi is not None:
        above_hi = value > constraint.hi or (
            value == constraint.hi and not constraint.hi_inclusive
        )
        if above_hi:
            return f"{_format_value(value)} > {_format_value(constraint.hi)}"
    return f"{_format_value(value)} is outside {describe(constraint, unit)}"


def describe(constraint: Constraint, unit: UnitKind) -> str:
    """Human-readable summary used in findings and answers."""

    def fmt(value: Decimal) -> str:
        text = format(value.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    unit_text = "approvals" if unit is UnitKind.APPROVALS else "years"
    if constraint.lo is not None and constraint.hi is not None:
        if constraint.lo == constraint.hi and constraint.lo_inclusive and constraint.hi_inclusive:
            return f"exactly {fmt(constraint.lo)} {unit_text}"
        return (
            f"{fmt(constraint.lo)}"
            f"{'<=' if constraint.lo_inclusive else '<'} value "
            f"{'<=' if constraint.hi_inclusive else '<'}{fmt(constraint.hi)} {unit_text}"
        )
    if constraint.lo is not None:
        return (
            f"at least {fmt(constraint.lo)} {unit_text}"
            if constraint.lo_inclusive
            else f"more than {fmt(constraint.lo)} {unit_text}"
        )
    if constraint.hi is not None:
        return (
            f"at most {fmt(constraint.hi)} {unit_text}"
            if constraint.hi_inclusive
            else f"fewer than {fmt(constraint.hi)} {unit_text}"
        )
    return f"unspecified {unit_text}"  # pragma: no cover - defensive
