"""The ledger: every dollar logged against a benefit, when, how much, by whom."""

from datetime import date

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN
from custom_components.cardperks.coordinator import seed_ledger
from custom_components.cardperks.models import StateDocument

from .conftest import CARD_ID


async def test_ledger_records_manual_and_statement_entries(
    hass, setup_integration: MockConfigEntry
):
    entry = setup_integration
    coord = entry.runtime_data
    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_ledger")

    coord.mark_used(CARD_ID, "monthly_credit", 4, date(2026, 9, 3), "coffee")
    coord.set_used(CARD_ID, "monthly_credit", 10)  # +6
    assert coord.record_statement_usage(
        CARD_ID, "travel_credit", date(2026, 8, 20), 112.94, "TRAVEL CREDIT $300/YEAR"
    )
    coord.commit()
    coord.reset_benefit(CARD_ID, "monthly_credit")  # -10
    await hass.async_block_till_done()

    st = hass.states.get(eid)
    assert st.state == "4"
    rows = st.attributes["entries"]
    assert [(r["on"], r["benefit"], r["amount"], r["source"]) for r in rows] == [
        ("2026-09-05", "Monthly credit (monthly)", -10.0, "manual"),
        ("2026-09-05", "Monthly credit (monthly)", 6.0, "manual"),
        ("2026-09-03", "Monthly credit (monthly)", 4.0, "manual"),
        ("2026-08-20", "Travel credit", 112.94, "statement"),
    ]
    assert rows[2]["note"] == "coffee" and rows[0]["note"] == "reset"
    assert st.attributes["total_12m"] == 112.94


def test_ledger_is_seeded_from_statement_keys_once():
    doc = StateDocument(
        imported_refs={
            "c1:travel_credit:2026-07-22:112.94:TRAVEL CREDIT $300/YEAR",
            "c1:dining_credit:2026-05-16:150.00:DINING CREDIT $300/YEAR",
        }
    )
    assert seed_ledger(doc) == 2
    assert [(r["on"], r["benefit_id"], r["amount"], r["source"]) for r in doc.ledger] == [
        ("2026-05-16", "dining_credit", 150.0, "statement"),
        ("2026-07-22", "travel_credit", 112.94, "statement"),
    ]
    assert seed_ledger(doc) == 0  # never twice


async def test_ledger_windows(hass, setup_integration: MockConfigEntry):
    """Totals per window, and the shared picker that the card pages follow."""
    entry = setup_integration
    coord = entry.runtime_data
    coord.mark_used(CARD_ID, "monthly_credit", 4, date(2026, 9, 3))  # YTD, T12
    assert coord.record_statement_usage(
        CARD_ID, "travel_credit", date(2025, 12, 20), 100.0, "TRAVEL CREDIT $300/YEAR"
    )  # prior year, and within T12
    assert coord.record_statement_usage(
        CARD_ID, "travel_credit", date(2025, 3, 1), 50.0, "TRAVEL CREDIT $300/YEAR"
    )  # prior year only
    coord.commit()
    await hass.async_block_till_done()

    reg = er.async_get(hass)
    st = hass.states.get(reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_ledger"))
    assert st.attributes["totals"] == {
        "year_to_date": 4.0,
        "prior_year": 150.0,
        "trailing_12_months": 104.0,
        "all": 154.0,
    }
    assert st.attributes["window"] == "trailing_12_months"

    picker = reg.async_get_entity_id("select", DOMAIN, "ledger_window")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": picker, "option": "prior_year"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(picker).state == "prior_year"
    assert hass.states.get(picker).attributes["from"] == "2025-01-01"
    st = hass.states.get(reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_ledger"))
    assert st.attributes["window"] == "prior_year"


async def test_mark_used_with_a_past_date_lands_in_that_period(hass, setup_integration):
    """Uber Cash never shows on a statement: marking a past month used after the fact
    goes into that month's record, not the current one, and the ledger says manual."""
    coord = setup_integration.runtime_data
    coord.mark_used(CARD_ID, "monthly_credit", None, date(2026, 6, 10), "Uber rides that month")
    await hass.async_block_till_done()
    rec = next(
        h
        for h in coord.doc.history
        if h.benefit_id == "monthly_credit" and h.period_start == "2026-06-01"
    )
    assert rec.amount_used == 10.0 and rec.final_status == "used" and rec.closed_by == "manual"
    inst = coord.instance(CARD_ID, "monthly_credit")
    assert inst.amount_used == 0.0  # the current month is untouched
    line = coord.ledger_for(CARD_ID)[0]
    assert line["on"] == "2026-06-10" and line["source"] == "manual" and line["amount"] == 10.0
    reg = er.async_get(hass)
    ps = hass.states.get(
        reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_monthly_credit_status")
    ).attributes["periods"]
    assert ps[5]["outcome"] == "captured"
