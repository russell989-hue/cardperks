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
