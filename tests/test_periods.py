"""Pure tests for period math."""

from datetime import date

import pytest

from custom_components.cardperks.const import Cadence, ResetRule
from custom_components.cardperks.periods import (
    Period,
    add_months,
    compute_period,
    next_fee_date,
    period_after,
)


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
        (date(2026, 9, 5), -24, date(2024, 9, 5)),
    ],
)
def test_add_months(start, n, expected):
    assert add_months(start, n) == expected


@pytest.mark.parametrize(
    ("today", "cadence", "reset", "open_date", "fee_month", "expected"),
    [
        # calendar resets
        (
            date(2026, 9, 5),
            Cadence.MONTHLY,
            ResetRule.CALENDAR,
            None,
            None,
            Period(date(2026, 9, 1), date(2026, 9, 30)),
        ),
        (
            date(2026, 9, 5),
            Cadence.QUARTERLY,
            ResetRule.CALENDAR,
            None,
            None,
            Period(date(2026, 7, 1), date(2026, 9, 30)),
        ),
        (
            date(2026, 9, 5),
            Cadence.SEMIANNUAL,
            ResetRule.CALENDAR,
            None,
            None,
            Period(date(2026, 7, 1), date(2026, 12, 31)),
        ),
        (
            date(2026, 6, 30),
            Cadence.SEMIANNUAL,
            ResetRule.CALENDAR,
            None,
            None,
            Period(date(2026, 1, 1), date(2026, 6, 30)),
        ),
        (
            date(2026, 9, 5),
            Cadence.ANNUAL,
            ResetRule.CALENDAR,
            None,
            None,
            Period(date(2026, 1, 1), date(2026, 12, 31)),
        ),
        # cardmember year anchored on open date
        (
            date(2026, 9, 5),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 3, 15),
            None,
            Period(date(2026, 3, 15), date(2027, 3, 14)),
        ),
        (
            date(2026, 3, 14),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 3, 15),
            None,
            Period(date(2025, 3, 15), date(2026, 3, 14)),
        ),
        (
            date(2026, 9, 5),
            Cadence.SEMIANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 3, 15),
            None,
            Period(date(2026, 3, 15), date(2026, 9, 14)),
        ),
        (
            date(2026, 9, 14),
            Cadence.SEMIANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 3, 15),
            None,
            Period(date(2026, 3, 15), date(2026, 9, 14)),
        ),
        (
            date(2026, 9, 15),
            Cadence.SEMIANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 3, 15),
            None,
            Period(date(2026, 9, 15), date(2027, 3, 14)),
        ),
        # fee month only: day defaults to 1
        (
            date(2026, 9, 5),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            None,
            11,
            Period(date(2025, 11, 1), date(2026, 10, 31)),
        ),
        (
            date(2026, 11, 1),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            None,
            11,
            Period(date(2026, 11, 1), date(2027, 10, 31)),
        ),
        # fee month plus matching open date keeps the day
        (
            date(2026, 9, 5),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2020, 11, 20),
            11,
            Period(date(2025, 11, 20), date(2026, 11, 19)),
        ),
        # per_anniversary ignores reset=calendar
        (
            date(2026, 9, 5),
            Cadence.PER_ANNIVERSARY,
            ResetRule.CALENDAR,
            date(2024, 3, 15),
            None,
            Period(date(2026, 3, 15), date(2027, 3, 14)),
        ),
        # leap-day anniversary clamps
        (
            date(2026, 9, 5),
            Cadence.ANNUAL,
            ResetRule.CARDMEMBER_YEAR,
            date(2024, 2, 29),
            None,
            Period(date(2026, 2, 28), date(2027, 2, 27)),
        ),
        # monthly on the 31st never drifts
        (
            date(2026, 4, 15),
            Cadence.MONTHLY,
            ResetRule.CARDMEMBER_YEAR,
            date(2025, 1, 31),
            None,
            Period(date(2026, 3, 31), date(2026, 4, 29)),
        ),
    ],
)
def test_compute_period(today, cadence, reset, open_date, fee_month, expected):
    assert compute_period(today, cadence, reset, open_date, fee_month) == expected


def test_compute_period_unanchored_returns_none():
    assert (
        compute_period(date(2026, 9, 5), Cadence.ANNUAL, ResetRule.CARDMEMBER_YEAR, None, None)
        is None
    )


def test_one_time():
    assert compute_period(
        date(2026, 9, 5), Cadence.ONE_TIME, ResetRule.CALENDAR, date(2026, 8, 1), None, 90
    ) == Period(date(2026, 8, 1), date(2026, 10, 30))
    assert compute_period(
        date(2026, 9, 5), Cadence.ONE_TIME, ResetRule.CALENDAR, date(2026, 8, 1), None
    ) == Period(date(2026, 8, 1), None)
    assert compute_period(
        date(2026, 9, 5), Cadence.ONE_TIME, ResetRule.CALENDAR, None, None, 90
    ) == Period(date(2026, 9, 5), None)


def test_period_after_chains_without_drift():
    p = compute_period(
        date(2026, 1, 31), Cadence.MONTHLY, ResetRule.CARDMEMBER_YEAR, date(2025, 1, 31), None
    )
    assert p == Period(date(2026, 1, 31), date(2026, 2, 27))
    p = period_after(p.end, Cadence.MONTHLY, ResetRule.CARDMEMBER_YEAR, date(2025, 1, 31), None)
    assert p == Period(date(2026, 2, 28), date(2026, 3, 30))
    p = period_after(p.end, Cadence.MONTHLY, ResetRule.CARDMEMBER_YEAR, date(2025, 1, 31), None)
    assert p == Period(date(2026, 3, 31), date(2026, 4, 29))


@pytest.mark.parametrize(
    ("today", "open_date", "fee_month", "expected"),
    [
        (date(2026, 9, 5), date(2024, 3, 15), None, date(2027, 3, 15)),
        (date(2026, 3, 15), date(2024, 3, 15), None, date(2027, 3, 15)),
        (date(2026, 3, 14), date(2024, 3, 15), None, date(2026, 3, 15)),
        (date(2026, 12, 20), None, 1, date(2027, 1, 1)),
        (date(2026, 9, 5), None, None, None),
    ],
)
def test_next_fee_date(today, open_date, fee_month, expected):
    assert next_fee_date(today, open_date, fee_month) == expected
