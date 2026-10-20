"""Scope applicability, discrete amount intervals and half-open time intervals.

Amount intersections use explicit endpoint inclusion so an included singleton
intersection is detected (never a strict ``<`` endpoint test).
"""

from __future__ import annotations

from datetime import datetime

from ..contracts.common import (
    AmountInterval,
    AmountScope,
    RecordScope,
    PolicyScope,
    Scope,
    TimeInterval,
    TimeInterval as _TimeInterval,
)
from ..contracts.qa import TargetFacts


def _lower_bounds(a: int | None, a_incl: bool, b: int | None, b_incl: bool) -> tuple[int | None, bool]:
    if a is None:
        return b, b_incl
    if b is None:
        return a, a_incl
    if a > b:
        return a, a_incl
    if b > a:
        return b, b_incl
    return a, a_incl and b_incl


def _upper_bounds(a: int | None, a_incl: bool, b: int | None, b_incl: bool) -> tuple[int | None, bool]:
    if a is None:
        return b, b_incl
    if b is None:
        return a, a_incl
    if a < b:
        return a, a_incl
    if b < a:
        return b, b_incl
    return a, a_incl and b_incl


def amount_intersection(a: AmountInterval, b: AmountInterval) -> AmountInterval | None:
    lower, lower_incl = _lower_bounds(a.lower, a.lower_inclusive, b.lower, b.lower_inclusive)
    upper, upper_incl = _upper_bounds(a.upper, a.upper_inclusive, b.upper, b.upper_inclusive)
    if lower is None and upper is None:
        # Both operands are bounded on at least one side, so this cannot happen.
        return None  # pragma: no cover - defensive
    if lower is not None and upper is not None:
        if lower > upper:
            return None
        if lower == upper and not (lower_incl and upper_incl):
            return None
    try:
        return AmountInterval(
            lower=lower,
            lower_inclusive=lower_incl,
            upper=upper,
            upper_inclusive=upper_incl,
        )
    except ValueError:
        return None


def amount_interval_covers(outer: AmountInterval, inner: AmountInterval) -> bool:
    """True when every amount in ``inner`` is also in ``outer``."""

    intersection = amount_intersection(outer, inner)
    if intersection is None:
        return False
    return intersection == inner


def time_intersection(a: TimeInterval, b: TimeInterval) -> TimeInterval | None:
    start = a.start if b.start is None else b.start if a.start is None else max(a.start, b.start)
    end = a.end if b.end is None else b.end if a.end is None else min(a.end, b.end)
    if start is not None and end is not None and start >= end:
        return None
    return TimeInterval(start=start, end=end)


def time_covers(outer: TimeInterval, inner: TimeInterval) -> bool:
    intersection = time_intersection(outer, inner)
    return intersection == inner


def valid_interval(start: datetime | None, end: datetime | None) -> TimeInterval | None:
    if start is not None and end is not None and start >= end:
        return None
    return TimeInterval(start=start, end=end)


def scope_intersection(a: Scope, b: Scope) -> Scope | None:
    """Applicability intersection for two claim scopes.

    Loan scopes intersect on matching currency, loan type, originating office and
    overlapping amount bands.  Record scopes are categorical: every field must match.
    """

    if isinstance(a, PolicyScope) and isinstance(b, PolicyScope):
        # Description equality is not semantic scope equality. Only explicit
        # categorical conflicts can be ruled out here; the model checks the rest.
        if any(key in b.attributes and b.attributes[key] != value
               for key, value in a.attributes.items()):
            return None
        if a == b:
            return a
        return PolicyScope(
            description=" / ".join(sorted({a.description, b.description}))[:1000],
            attributes={**a.attributes, **b.attributes},
        )
    if isinstance(a, AmountScope) and isinstance(b, AmountScope):
        if a.loan_type is not b.loan_type or a.currency is not b.currency:
            return None
        if a.origin_office is not b.origin_office:
            return None
        amounts = amount_intersection(a.amount_minor, b.amount_minor)
        if amounts is None:
            return None
        return AmountScope(
            loan_type=a.loan_type,
            currency=a.currency,
            origin_office=a.origin_office,
            amount_minor=amounts,
        )
    if isinstance(a, RecordScope) and isinstance(b, RecordScope):
        if (
            a.record_class is b.record_class
            and a.origin_office is b.origin_office
            and a.processing_office is b.processing_office
            and a.product is b.product
            and a.starting_event is b.starting_event
        ):
            return RecordScope(
                record_class=a.record_class,
                origin_office=a.origin_office,
                processing_office=b.processing_office,
                product=a.product,
                starting_event=a.starting_event,
            )
        return None
    return None


def scope_matches_target(scope: Scope, target: TargetFacts) -> bool:
    """True when ``scope`` applies to the explicit typed target facts."""

    if isinstance(scope, PolicyScope):
        return False  # General policy Q&A is not part of the numeric answer engine.
    if isinstance(scope, AmountScope):
        if target.subject.value != "loan_approval":
            return False
        if target.amount_minor is None or target.currency is None or target.loan_type is None:
            return False
        if target.origin_office is None:
            return False
        return (
            scope.currency is target.currency
            and scope.loan_type is target.loan_type
            and scope.origin_office is target.origin_office
            and scope.amount_minor.contains(target.amount_minor)
        )
    if target.subject.value != "record_retention":
        return False
    if target.record_class is None or target.starting_event is None:
        return False
    if target.origin_office is not None and scope.origin_office is not target.origin_office:
        return False
    if target.processing_office is not None and scope.processing_office is not target.processing_office:
        return False
    if target.product is not None and scope.product is not target.product:
        return False
    return (
        scope.record_class is target.record_class
        and scope.starting_event is target.starting_event
    )


def format_amount_minor(amount_minor: int) -> str:
    """Deterministic USD rendering of minor units (no banker's rounding games)."""

    sign = "-" if amount_minor < 0 else ""
    whole, cents = divmod(abs(amount_minor), 100)
    return f"{sign}USD {whole:,}.{cents:02d}"


def format_amount_interval(interval: AmountInterval) -> str:
    lower = (
        "0" if interval.lower is None else format_amount_minor(interval.lower)
    )
    if interval.lower is not None:
        lower = f"{'[' if interval.lower_inclusive else '('}{lower}"
    else:
        lower = "(unbounded_min"
    upper = (
        "unbounded_max" if interval.upper is None else format_amount_minor(interval.upper)
    )
    if interval.upper is not None:
        upper = f"{upper}{']' if interval.upper_inclusive else ')'}"
    else:
        upper = f"{upper})"
    return f"{lower}, {upper}"


def format_time_interval(interval: _TimeInterval | None) -> str:
    if interval is None:
        return "unspecified"
    start = interval.start.isoformat() if interval.start else "unbounded"
    end = interval.end.isoformat() if interval.end else "unbounded"
    return f"[{start}, {end})"
