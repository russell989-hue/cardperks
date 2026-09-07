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
    # Step 1: owner and program. "Another program" means typing it in on step 2.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"owner_id": OWNER_ID, "program_id": "__other__"}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "details"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
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


async def test_status_from_a_catalog_program(hass, setup_integration: MockConfigEntry):
    """A program in the catalog offers its tiers and brings their benefits along."""
    entry = setup_integration
    assert "test_air" in entry.runtime_data.catalog.programs

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "status"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"owner_id": OWNER_ID, "program_id": "test_air"}
    )
    assert result["step_id"] == "details"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"tier_id": "gold", "valid_through": "2027-01-31"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Air Miles Elite Gold (Brian)"
    await hass.async_block_till_done()

    sub = next(s for s in entry.subentries.values() if s.subentry_type == "status")
    assert sub.data["program_id"] == "test_air" and sub.data["tier_id"] == "gold"
    st = hass.states.get(_eid(hass, f"status_{sub.subentry_id}"))
    assert st.state == "Elite Gold"
    a = st.attributes
    assert a["tier_rank"] == 2 and a["tier_benefits"] == ["2 free bags", "Lounge passes"]
    assert a["how_earned"] == "10,000 points"
    assert a["next_tier"] == "Elite Platinum" and a["next_tier_qualify"] == "15,000 points"
    assert a["source"] == "entered by hand"


async def test_status_unlocks_a_conditional_benefit(hass, setup_integration: MockConfigEntry):
    """A benefit with `requires_status` turns on by itself once the holder has the tier."""
    entry = setup_integration
    reg = er.async_get(hass)
    # Nobody holds Test Air Gold yet: the status bonus stays off.
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_status_bonus_status") is None

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "status"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"owner_id": OWNER_ID, "program_id": "test_air"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"tier_id": "platinum", "valid_through": "2027-01-31"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Platinum outranks the Gold the benefit asks for, so it is on for Brian's card...
    coord = entry.runtime_data
    assert "status_bonus" in coord.cards[CARD_ID].enabled_conditional
    assert hass.states.get(_eid(hass, f"{CARD_ID}_status_bonus_status")).state == "unused"
    # ...and not for Nick's, who holds no status (and is an authorized user anyway).
    assert "status_bonus" not in coord.cards[AU_CARD_ID].enabled_conditional


async def test_lapsed_status_does_not_qualify(hass, setup_integration: MockConfigEntry):
    """A status past its valid-through date no longer unlocks anything."""
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "status"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"owner_id": OWNER_ID, "program_id": "test_air"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"tier_id": "gold", "valid_through": "2026-01-31"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "status_bonus" not in entry.runtime_data.cards[CARD_ID].enabled_conditional


async def test_status_by_name_qualifies(hass, setup_integration: MockConfigEntry):
    """A status typed in by hand matches the program and tier by name."""
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "status"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"owner_id": OWNER_ID, "program_id": "__other__"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "program": "Test Air Miles",
            "tier": "elite gold",
            "valid_through": "2027-06-01",
            "source": "flown",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "status_bonus" in entry.runtime_data.cards[CARD_ID].enabled_conditional
