"""The CardPerks calendar: fees, review reminders, statuses lapsing, and your own notes."""

from datetime import UTC, datetime

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN


async def _events(hass, entity_id, start, end):
    resp = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": entity_id, "start_date_time": start, "end_date_time": end},
        blocking=True,
        return_response=True,
    )
    return resp[entity_id]["events"]


async def test_calendar_lists_fees_reviews_and_statuses(hass, setup_integration: MockConfigEntry):
    """A year ahead: each card's fee date, a review 30 days before it, and statuses lapsing."""
    eid = er.async_get(hass).async_get_entity_id("calendar", DOMAIN, "cardperks_calendar")
    assert eid
    events = await _events(hass, eid, "2026-09-05T00:00:00+00:00", "2027-09-05T00:00:00+00:00")
    by_summary = {e["summary"]: e for e in events}

    # The premium card opened 2026-07-01 with a $500 fee: due 2027-07-01, review 2027-06-01.
    fee = by_summary["$500 annual fee: Premium Card (Brian | 1234)"]
    assert fee["start"] == "2027-07-01" and fee["end"] == "2027-07-02"
    review = by_summary["Review Premium Card (Brian | 1234) before its $500 fee"]
    assert review["start"] == "2027-06-01"
    # A card-granted status renews with the card, so it is not a calendar event.
    assert not any(s.startswith("Test Lounge Club Gold lapses") for s in by_summary)
    # Perks are not "used by" a date: the $100 lounge perk is not listed as closing.
    assert not any("Lounge access" in s for s in by_summary)
    # Big credits still unused close on their period's last day: the $150 dining credit.
    dining = by_summary[
        "Use $150 Dining credit (every 6 months) by today: Premium Card (Brian | 1234)"
    ]
    assert dining["start"] == "2026-12-31"

    # The next event, as the entity state.
    st = hass.states.get(eid)
    assert st.state == "off"  # nothing today
    assert st.attributes["message"].startswith(("Review", "$", "Use $", "Test Lounge Club"))


async def test_own_reminders_can_be_added_and_removed(hass, setup_integration: MockConfigEntry):
    """A reminder created from the calendar UI is kept and can be deleted again."""
    entry = setup_integration
    eid = er.async_get(hass).async_get_entity_id("calendar", DOMAIN, "cardperks_calendar")
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": eid,
            "summary": "Cancel NYT before the introductory rate ends",
            "description": "Six-month intro from 2026-09-06.",
            "start_date": "2027-03-01",
            "end_date": "2027-03-02",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    events = await _events(hass, eid, "2027-02-01T00:00:00+00:00", "2027-04-01T00:00:00+00:00")
    mine = [e for e in events if e["summary"].startswith("Cancel NYT")]
    assert len(mine) == 1 and mine[0]["start"] == "2027-03-01"
    reminders = entry.runtime_data.doc.reminders
    assert len(reminders) == 1 and reminders[0]["summary"].startswith("Cancel NYT")

    # Delete it through the entity, the way the calendar UI does.
    calendar = next(
        e for e in hass.data["entity_components"]["calendar"].entities if e.entity_id == eid
    )
    await calendar.async_delete_event(reminders[0]["uid"])
    await hass.async_block_till_done()
    assert entry.runtime_data.doc.reminders == []
    assert not [
        e
        for e in await _events(hass, eid, "2027-02-01T00:00:00+00:00", "2027-04-01T00:00:00+00:00")
        if e["summary"].startswith("Cancel NYT")
    ]
    assert datetime.now(UTC)  # keeps the import used if the file grows
