"""Pure tests for the rollover function."""

from datetime import date

from custom_components.cardperks.const import BenefitStatus, Role
from custom_components.cardperks.models import HeldCard, StateDocument, instance_key
from custom_components.cardperks.rollover import rollover

NOW = "2026-09-05T10:00:00+00:00"


def _card(**kw) -> HeldCard:
    base = dict(
        id="c1",
        owner_id="o1",
        product_id="test_premium",
        role=Role.PRIMARY,
        title="Premium",
        open_date=date(2024, 3, 15),
    )
    base.update(kw)
    return HeldCard(**base)


def test_opens_all_benefits_for_primary(catalog):
    doc = StateDocument()
    result = rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    assert result.opened == 5 and result.changed
    keys = set(doc.instances)
    assert keys == {
        f"c1:{b}" for b in ("monthly_credit", "dining_credit", "travel_credit", "lounge", "sub")
    }
    inst = doc.instances["c1:travel_credit"]
    assert (inst.period_start, inst.period_end) == ("2026-03-15", "2027-03-14")
    assert inst.amount == 300 and inst.status is BenefitStatus.UNUSED
    assert doc.instances["c1:lounge"].amount == 100  # perk default value
    assert doc.last_rollover == "2026-09-05"


def test_au_only_gets_own_allotment_benefits(catalog):
    doc = StateDocument()
    au = _card(id="au", role=Role.AUTHORIZED_USER, parent_card_id="c1")
    rollover(doc, [au], catalog, date(2026, 9, 5), NOW)
    assert set(doc.instances) == {"au:lounge"}


def test_idempotent(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    second = rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    assert not second.changed and second.opened == 0 and second.closed == 0


def test_rolls_monthly_and_records_history(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    doc.instances["c1:monthly_credit"].status = BenefitStatus.PARTIAL
    doc.instances["c1:monthly_credit"].amount_used = 4.0
    result = rollover(doc, [_card()], catalog, date(2026, 10, 1), NOW)
    assert result.closed == 1 and result.opened == 1 and result.gaps == 0
    hist = [h for h in doc.history if h.benefit_id == "monthly_credit"]
    assert len(hist) == 1
    assert (
        hist[0].final_status == "partial"
        and hist[0].amount_used == 4.0
        and hist[0].closed_by == "rollover"
    )
    assert doc.instances["c1:monthly_credit"].period_start == "2026-10-01"
    assert doc.instances["c1:monthly_credit"].status is BenefitStatus.UNUSED


def test_missed_periods_become_gap_history(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    result = rollover(doc, [_card()], catalog, date(2026, 12, 3), NOW)
    monthly = [h for h in doc.history if h.benefit_id == "monthly_credit"]
    assert [h.period_start for h in monthly] == ["2026-09-01", "2026-10-01", "2026-11-01"]
    assert [h.closed_by for h in monthly] == ["rollover", "gap", "gap"]
    assert monthly[1].final_status == "unknown"
    assert result.gaps == 2
    assert doc.instances["c1:monthly_credit"].period_start == "2026-12-01"
    # semiannual dining credit rolled once, no gap
    dining = [h for h in doc.history if h.benefit_id == "dining_credit"]
    assert dining == []  # Jul-Dec period still open on Dec 3


def test_sticky_na_carries_over(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    inst = doc.instances["c1:monthly_credit"]
    inst.status = BenefitStatus.NA
    inst.sticky_na = True
    rollover(doc, [_card()], catalog, date(2026, 10, 2), NOW)
    new = doc.instances["c1:monthly_credit"]
    assert new.status is BenefitStatus.NA and new.sticky_na


def test_one_time_closes_and_never_reopens(catalog):
    doc = StateDocument()
    card = _card(open_date=date(2026, 7, 1))
    rollover(doc, [card], catalog, date(2026, 9, 5), NOW)
    assert doc.instances["c1:sub"].period_end == "2026-09-29"
    assert doc.instances["c1:sub"].amount is None  # points carry no dollar amount
    rollover(doc, [card], catalog, date(2026, 10, 15), NOW)
    assert "c1:sub" not in doc.instances
    assert any(h.benefit_id == "sub" for h in doc.history)
    rollover(doc, [card], catalog, date(2026, 11, 15), NOW)
    assert "c1:sub" not in doc.instances
    assert sum(1 for h in doc.history if h.benefit_id == "sub") == 1


def test_one_time_already_expired_is_not_opened(catalog):
    doc = StateDocument()
    card = _card(open_date=date(2025, 1, 1))
    rollover(doc, [card], catalog, date(2026, 9, 5), NOW)
    assert "c1:sub" not in doc.instances


def test_reanchor_when_open_date_changes(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    rollover(doc, [_card(open_date=date(2024, 6, 1))], catalog, date(2026, 9, 5), NOW)
    inst = doc.instances["c1:travel_credit"]
    assert inst.period_start == "2026-06-01"
    assert any(h.closed_by == "reanchor" and h.benefit_id == "travel_credit" for h in doc.history)


def test_closed_card_closes_instances(catalog):
    doc = StateDocument()
    rollover(doc, [_card()], catalog, date(2026, 9, 5), NOW)
    closed = _card(close_date=date(2026, 9, 10))
    rollover(doc, [closed], catalog, date(2026, 9, 20), NOW)
    assert not any(k.startswith("c1:") for k in doc.instances)
    assert all(h.closed_by == "closed_card" for h in doc.history)


def test_unanchored_card_gets_calendar_benefits_only(catalog):
    doc = StateDocument()
    rollover(doc, [_card(open_date=None, fee_month=None)], catalog, date(2026, 9, 5), NOW)
    assert set(doc.instances) == {
        instance_key("c1", b) for b in ("monthly_credit", "dining_credit", "sub")
    }
