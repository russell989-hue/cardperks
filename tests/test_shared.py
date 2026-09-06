"""Shared perks: one household value, split across the cards that carry it."""

from types import MappingProxyType

import pytest
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN

from .conftest import AU_CARD_ID, CARD_ID, card_subentry

BASIC_ID = "card_basic_1"


def _eid(hass, domain, unique_id):
    eid = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert eid, unique_id
    return eid


async def _add_basic_card(hass, entry) -> None:
    d = card_subentry(
        subentry_id=BASIC_ID,
        product_id="test_basic",
        last4="5555",
        title="Basic Card (Brian | 5555)",
    )
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(d["data"]),
            subentry_type=d["subentry_type"],
            title=d["title"],
            unique_id=None,
            subentry_id=d["subentry_id"],
        ),
    )
    await hass.async_block_till_done()


async def test_shared_perk_is_valued_once_and_split(hass, setup_integration: MockConfigEntry):
    """Priority Pass on three cards is one membership: one number, three equal shares."""
    entry = setup_integration
    await _add_basic_card(hass, entry)
    reg = er.async_get(hass)

    # No per-card value number for a shared perk; one household number instead.
    assert reg.async_get_entity_id("number", DOMAIN, f"{CARD_ID}_priority_pass_value") is None
    household = _eid(hass, "number", "shared_priority_pass_value")
    st = hass.states.get(household)
    assert st.state == "0.0" and st.attributes["kind"] == "shared_value"
    assert st.attributes["card"] == "All cards" and len(st.attributes["cards"]) == 3
    # The unshared lounge perk keeps its own per-card number.
    assert reg.async_get_entity_id("number", DOMAIN, f"{CARD_ID}_lounge_value")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": household, "value": 300}, blocking=True
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(household).state) == 300.0
    assert hass.states.get(household).attributes["per_card"] == 100.0
    for card_id in (CARD_ID, AU_CARD_ID, BASIC_ID):
        status = hass.states.get(_eid(hass, "sensor", f"{card_id}_priority_pass_status"))
        assert status.attributes["amount"] == 100.0, card_id
        remaining = hass.states.get(_eid(hass, "sensor", f"{card_id}_priority_pass_remaining"))
        assert float(remaining.state) == 100.0

    # The share shows up in the card's own totals, and the household number is not
    # counted three times over.
    coord = entry.runtime_data
    assert coord.data.card_summaries[CARD_ID].benefit_totals["priority_pass"].annual_value == 100.0
    assert coord.data.shared_perks["priority_pass"].value == 300.0

    # Freeze one card: its share moves to the others.
    coord.set_card_status(BASIC_ID, "frozen")
    await hass.async_block_till_done()
    assert hass.states.get(household).attributes["per_card"] == 150.0
    for card_id in (CARD_ID, AU_CARD_ID):
        status = hass.states.get(_eid(hass, "sensor", f"{card_id}_priority_pass_status"))
        assert status.attributes["amount"] == 150.0

    # Marking it used captures the share, and a later resplit keeps used == amount.
    coord.mark_used(CARD_ID, "priority_pass")
    coord.set_card_status(BASIC_ID, "active")
    await hass.async_block_till_done()
    status = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_priority_pass_status"))
    assert status.state == "used" and status.attributes["amount_used"] == 100.0

    # The per-card service refuses a shared perk and points at the household number.
    with pytest.raises(ServiceValidationError):
        coord.set_perk_value(CARD_ID, "priority_pass", 50)

    # The value survives a reload.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(_eid(hass, "number", "shared_priority_pass_value")).state) == 300.0


def test_per_card_values_seed_the_household_number(catalog):
    """A value typed on one card before sharing existed becomes the household's number."""

    from custom_components.cardperks.const import Role
    from custom_components.cardperks.coordinator import seed_shared_values
    from custom_components.cardperks.models import HeldCard, StateDocument

    cards = [
        HeldCard(id="a", owner_id="o", product_id="test_premium", role=Role.PRIMARY, title="A"),
        HeldCard(id="b", owner_id="o", product_id="test_basic", role=Role.PRIMARY, title="B"),
    ]
    benefit = catalog.get("test_premium").benefit("priority_pass")
    members = {"priority_pass": [(cards[0], benefit), (cards[1], benefit)]}

    doc = StateDocument(perk_values={"a": {"priority_pass": 100.0, "lounge": 40.0}})
    assert seed_shared_values(doc, members) == 1
    assert doc.shared_values == {"priority_pass": 100.0}
    # Idempotent, and a household value already set is never overwritten.
    doc.shared_values["priority_pass"] = 250.0
    assert seed_shared_values(doc, members) == 0
    assert doc.shared_values["priority_pass"] == 250.0
    # Nothing typed anywhere: nothing seeded, the catalog default applies at runtime.
    assert seed_shared_values(StateDocument(), members) == 0
