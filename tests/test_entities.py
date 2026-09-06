"""Entity states, services, and persistence."""

from datetime import date

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN, STORAGE_KEY

from .conftest import AU_CARD_ID, CARD_ID, OWNER_ID


def _eid(hass, platform: str, unique_id: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert eid, unique_id
    return eid


async def test_entities_created(hass, setup_integration: MockConfigEntry):
    registry = er.async_get(hass)
    ours = [e for e in registry.entities.values() if e.platform == DOMAIN]
    # primary: 5 benefits x (select + expires + remaining + button) + 4 card-level = 24
    # AU: 1 benefit x 4 + 4 card-level = 8 ; owners: 2 x 4 = 8
    assert len(ours) == 24 + 8 + 8

    travel = hass.states.get(_eid(hass, "select", f"{CARD_ID}_travel_credit_status"))
    assert travel.state == "unused"
    assert travel.attributes["amount"] == 300 and travel.attributes["period_end"] == "2027-06-30"
    assert travel.name == "Premium Card (Brian ·1234) Travel credit"

    expires = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_expires"))
    assert expires.state == "2026-12-31" and expires.attributes["days_left"] == 117

    fee = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_fee_due"))
    assert fee.state == "2027-07-01"
    assert hass.states.get(_eid(hass, "binary_sensor", f"{CARD_ID}_fee_within_45d")).state == "off"

    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 150.0 and rem.attributes["percent_used"] == 0.0
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_sub_remaining")).state == "unknown"

    unused = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value"))
    assert float(unused.state) == 10 + 150 + 300 + 100  # sub has no dollar amount
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    assert float(net.state) == -500

    # AU device only has lounge, and hangs off the primary card
    dev_reg = dr.async_get(hass)
    au_dev = dev_reg.async_get_device_by_identifier(
        (DOMAIN, AU_CARD_ID), setup_integration.entry_id
    )
    primary_dev = dev_reg.async_get_device_by_identifier(
        (DOMAIN, CARD_ID), setup_integration.entry_id
    )
    assert au_dev.via_device_id == primary_dev.id
    assert primary_dev.manufacturer == "Test Bank" and primary_dev.model == "Premium Card"
    assert hass.states.get(_eid(hass, "select", f"{AU_CARD_ID}_lounge_status")).state == "unused"
    assert (
        er.async_get(hass).async_get_entity_id(
            "select", DOMAIN, f"{AU_CARD_ID}_travel_credit_status"
        )
        is None
    )

    # owner rollups
    assert (
        float(hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_unused_credits")).state)
        == 560
    )
    exp30 = hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_expiring_30d"))
    assert exp30.state == "1"  # September monthly credit
    assert exp30.attributes["items"][0]["benefit"] == "Monthly credit"
    assert hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_expiring_7d")).state == "0"
    five = hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_5_24"))
    assert five.state == "1" and five.attributes["under_5_24"] is True


async def test_select_and_button_and_services(
    hass, setup_integration: MockConfigEntry, hass_storage
):
    dining = _eid(hass, "select", f"{CARD_ID}_dining_credit_status")

    await hass.services.async_call(
        "select", "select_option", {"entity_id": dining, "option": "used"}, blocking=True
    )
    st = hass.states.get(dining)
    assert st.state == "used" and st.attributes["amount_used"] == 150
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == 410
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m")).state) == -350

    await hass.services.async_call(DOMAIN, "reset_benefit", {"entity_id": dining}, blocking=True)
    assert hass.states.get(dining).state == "unused"

    await hass.services.async_call(
        DOMAIN, "mark_used", {"entity_id": dining, "amount": 40, "note": "Resy"}, blocking=True
    )
    st = hass.states.get(dining)
    assert st.state == "partial" and st.attributes["amount_used"] == 40
    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 110.0 and rem.attributes["percent_used"] == 26.7
    assert st.attributes["uses"][0]["note"] == "Resy"
    await hass.services.async_call(DOMAIN, "mark_used", {"entity_id": dining}, blocking=True)
    assert hass.states.get(dining).state == "used"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{CARD_ID}_monthly_credit_mark_used")},
        blocking=True,
    )
    assert hass.states.get(_eid(hass, "select", f"{CARD_ID}_monthly_credit_status")).state == "used"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _eid(hass, "select", f"{CARD_ID}_lounge_status"), "option": "n_a"},
        blocking=True,
    )

    # persisted
    await hass.async_block_till_done()
    from homeassistant.helpers.storage import Store

    data = hass_storage.get(STORAGE_KEY)
    if data is None:  # delayed save not flushed yet; force it
        await setup_integration.runtime_data.store.async_save_document(
            setup_integration.runtime_data.doc
        )
        data = hass_storage[STORAGE_KEY]
    inst = data["data"]["benefit_instances"][f"{CARD_ID}:dining_credit"]
    assert inst["status"] == "used" and inst["amount_used"] == 150
    assert data["data"]["benefit_instances"][f"{CARD_ID}:lounge"]["sticky_na"] is True
    assert isinstance(Store, type)


async def test_device_services(hass, setup_integration: MockConfigEntry):
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, CARD_ID), setup_integration.entry_id
    )
    owner_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"owner:{OWNER_ID}"), setup_integration.entry_id
    )

    await hass.services.async_call(
        DOMAIN,
        "set_perk_value",
        {"device_id": device.id, "benefit_id": "lounge", "value": 250},
        blocking=True,
    )
    lounge = hass.states.get(_eid(hass, "select", f"{CARD_ID}_lounge_status"))
    assert lounge.attributes["amount"] == 250
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == 710

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_perk_value",
            {"device_id": device.id, "benefit_id": "travel_credit", "value": 1},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_perk_value",
            {"device_id": owner_device.id, "benefit_id": "lounge", "value": 1},
            blocking=True,
        )

    await hass.services.async_call(
        DOMAIN, "add_sub_spend", {"device_id": device.id, "amount": 1500}, blocking=True
    )
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    tracker = net.attributes["sub_tracker"]
    assert (
        tracker["required"] == 4000 and tracker["spent"] == 1500 and tracker["completed_on"] is None
    )
    await hass.services.async_call(
        DOMAIN, "add_sub_spend", {"device_id": device.id, "amount": 2600}, blocking=True
    )
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    assert net.attributes["sub_tracker"]["completed_on"] == date(2026, 9, 5).isoformat()
    assert hass.states.get(_eid(hass, "select", f"{CARD_ID}_sub_status")).state == "used"

    await hass.services.async_call(
        DOMAIN,
        "activate_rotating_category",
        {"device_id": device.id, "category": "gas"},
        blocking=True,
    )
    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 150.0 and rem.attributes["percent_used"] == 0.0
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_sub_remaining")).state == "unknown"

    unused = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value"))
    assert unused.attributes["rotating_activations"]["2026-Q3"]["category"] == "gas"


async def test_annual_fee_override(hass, mock_entry: MockConfigEntry):
    from custom_components.cardperks.const import CONF_ANNUAL_FEE

    sub = mock_entry.subentries[CARD_ID]
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_subentry(
        mock_entry, sub, data={**sub.data, CONF_ANNUAL_FEE: 450}
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    fee = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_fee_due"))
    assert fee.attributes["annual_fee"] == 450
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m")).state) == -450


async def test_state_survives_reload(hass, setup_integration: MockConfigEntry):
    dining = _eid(hass, "select", f"{CARD_ID}_dining_credit_status")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": dining, "option": "used"}, blocking=True
    )
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(dining).state == "used"
