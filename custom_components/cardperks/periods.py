"""Period math for benefit cadences. Pure functions, no Home Assistant imports."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from .const import CADENCE_MONTHS, Cadence, ResetRule


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date | None  # inclusive; None = never expires

    def contains(self, d: date) -> bool:
        return self.start <= d and (self.end is None or d <= self.end)


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def add_months(d: date, n: int) -> date:
    """Add n months, clamping the day to the length of the target month."""
    y, m = divmod(d.month - 1 + n, 12)
    return _clamp_day(d.year + y, m + 1, d.day)


def anniversary_anchor(open_date: date | None, fee_month: int | None) -> tuple[int, int]:
    """(month, day) of the cardmember anniversary."""
    if fee_month:
        day = open_date.day if open_date and open_date.month == fee_month else 1
        return fee_month, day
    if open_date:
        return open_date.month, open_date.day
    raise ValueError("need open_date or fee_month")


def anniversary_on_or_before(today: date, month: int, day: int) -> date:
    cand = _clamp_day(today.year, month, day)
    if cand > today:
        cand = _clamp_day(today.year - 1, month, day)
    return cand


def next_fee_date(today: date, open_date: date | None, fee_month: int | None) -> date | None:
    """The next anniversary strictly after today, or None if unknown."""
    try:
        month, day = anniversary_anchor(open_date, fee_month)
    except ValueError:
        return None
    last = anniversary_on_or_before(today, month, day)
    return add_months(last, 12)


def compute_period(
    today: date,
    cadence: Cadence,
    reset: ResetRule,
    open_date: date | None,
    fee_month: int | None,
    expires_days_after_open: int | None = None,
) -> Period | None:
    """Period containing `today` for this cadence and reset rule.

    Returns None when a cardmember-year period cannot be anchored.
    """
    if cadence is Cadence.ONE_TIME:
        if open_date is None:
            return Period(today, None)
        end = (
            open_date + timedelta(days=expires_days_after_open) if expires_days_after_open else None
        )
        return Period(open_date, end)

    n = CADENCE_MONTHS[cadence]
    if cadence is Cadence.PER_ANNIVERSARY:
        reset = ResetRule.CARDMEMBER_YEAR

    if reset is ResetRule.CALENDAR:
        k = (today.month - 1) // n
        start = date(today.year, k * n + 1, 1)
    else:
        try:
            month, day = anniversary_anchor(open_date, fee_month)
        except ValueError:
            return None
        anniv = anniversary_on_or_before(today, month, day)
        i = 0
        start = anniv
        # Step from the anniversary (not the previous sub-period) so the day never drifts.
        while add_months(anniv, (i + 1) * n) <= today:
            i += 1
            start = add_months(anniv, i * n)

    end = add_months(start, n) - timedelta(days=1)
    return Period(start, end)


def period_after(
    prev_end: date,
    cadence: Cadence,
    reset: ResetRule,
    open_date: date | None,
    fee_month: int | None,
) -> Period | None:
    """The period immediately following one that ended on prev_end."""
    return compute_period(prev_end + timedelta(days=1), cadence, reset, open_date, fee_month)
