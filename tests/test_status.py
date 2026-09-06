"""Loyalty status: granted by a card, or entered by hand."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN

from .conftest import AU_CARD_ID, CARD_ID, OWNER_ID


def _eid(hass, unique_id):
    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert eid, unique_id
    return eid


async def test_card_granted_status(hass, setup_integration: MockConfigEntry):
    """A status the catalog says a card confers exists while the card is held."""
    entry = setup_integration
    coord = entry.runtime_data
    sid = f"card_{CARD_ID}_lounge_test_lounge_club"
    st = hass.states.get(_eid(hass, f"status_{sid}"))
    assert st.state == "Gold"
    a = st.attributes
    assert a["program"] == "Test Lounge Club" and a["owner"] == "Brian" and a["from_card"]
    assert a["card_id"] == CARD_ID and a["valid_through"] == "2027-07-01"  # next anniversary
    assert a["days_left"] == 299 and a["expiring_soon"] is False
    # The authorized user holds the lounge perk too, so Nick has the status as well.
    assert (
        hass.states.get(_eid(hass, f"status_card_{AU_CARD_ID}_lounge_test_lounge_club")).state
        == "Gold"
    )

    # Freeze the card and the status goes with it.
    coord.set_card_status(CARD_ID, "frozen")
    await hass.async_block_till_done()
    assert sid not in coord.data.statuses
    assert hass.states.get(_eid(hass, f"status_{sid}")).state == "unavailable"


async def test_status_entered_by_hand(hass, setup_integration: MockConfigEntry):
    """A status earned outright is a subentry with its own expiry."""
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "status"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "owner_id": OWNER_ID,
            "program": "United MileagePlus",
            "tier": "Premier Gold",
            "valid_through": "2026-10-01",
            "source": "flown",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "United MileagePlus Premier Gold (Brian)"
    await hass.async_block_till_done()

    sub = next(s for s in entry.subentries.values() if s.subentry_type == "status")
    st = hass.states.get(_eid(hass, f"status_{sub.subentry_id}"))
    assert st.state == "Premier Gold"
    a = st.attributes
    assert a["source"] == "flown" and a["from_card"] is False and a["card"] is None
    assert a["days_left"] == 26 and a["expiring_soon"] is True
