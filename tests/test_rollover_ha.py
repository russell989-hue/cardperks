"""Rollover wired through Home Assistant's clock."""

from datetime import UTC, datetime

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.cardperks.const import DOMAIN

from .conftest import CARD_ID


def _eid(hass, platform: str, unique_id: str) -> str:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


async def test_midnight_rollover(hass, setup_integration: MockConfigEntry, freezer):
    monthly = _eid(hass, "select", f"{CARD_ID}_monthly_credit_status")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": monthly, "option": "partial"}, blocking=True
    )
    assert hass.states.get(monthly).attributes["period_start"] == "2026-09-01"

    freezer.move_to(datetime(2026, 10, 1, 0, 5, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    st = hass.states.get(monthly)
    assert st.state == "unused" and st.attributes["period_start"] == "2026-10-01"
    doc = setup_integration.runtime_data.doc
    hist = [h for h in doc.history if h.benefit_id == "monthly_credit"]
    assert len(hist) == 1 and hist[0].final_status == "partial"

    # second tick the same day changes nothing
    freezer.move_to(datetime(2026, 10, 1, 3, 0, 0, tzinfo=UTC))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len([h for h in doc.history if h.benefit_id == "monthly_credit"]) == 1


async def test_catch_up_after_downtime(hass, setup_integration: MockConfigEntry, freezer):
    entry = setup_integration
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    freezer.move_to(datetime(2026, 12, 3, 12, 0, 0, tzinfo=UTC))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    monthly = hass.states.get(_eid(hass, "select", f"{CARD_ID}_monthly_credit_status"))
    assert monthly.attributes["period_start"] == "2026-12-01"
    hist = [h for h in entry.runtime_data.doc.history if h.benefit_id == "monthly_credit"]
    assert [h.closed_by for h in hist] == ["rollover", "gap", "gap"]
    assert hist[1].final_status == "unknown"
