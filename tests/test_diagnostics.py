"""Diagnostics redaction."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from .conftest import CARD_ID


async def test_diagnostics_redacts_personal_fields(
    hass, hass_client, setup_integration: MockConfigEntry
):
    diag = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)
    card = next(s for s in diag["subentries"] if s["subentry_id"] == CARD_ID)
    assert card["data"]["last4"] == "**REDACTED**"
    assert card["title"] == "**REDACTED**"
    assert card["data"]["product_id"] == "test_premium"
    assert f"{CARD_ID}:travel_credit" in diag["state"]["benefit_instances"]
    assert "test_premium" in diag["catalog_products"]
