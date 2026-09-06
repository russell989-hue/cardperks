"""Device-targeted services: SUB spend, perk valuation, rotating categories."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_AMOUNT,
    ATTR_BENEFIT_ID,
    ATTR_CATEGORY,
    ATTR_CSV,
    ATTR_DATE,
    ATTR_DEVICE_ID,
    ATTR_NOTE,
    ATTR_QUARTER,
    ATTR_VALUE,
    DATA_IMPORTING,
    DOMAIN,
    SERVICE_ACTIVATE_ROTATING_CATEGORY,
    SERVICE_ADD_SUB_SPEND,
    SERVICE_IMPORT_CARDS,
    SERVICE_SET_PERK_VALUE,
)
from .coordinator import CardPerksCoordinator
from .helpers import async_get_catalog
from .importer import async_import_cards

IMPORT_CARDS_SCHEMA = vol.Schema({vol.Required(ATTR_CSV): cv.string})

ADD_SUB_SPEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_AMOUNT): vol.Coerce(float),
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)

SET_PERK_VALUE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_BENEFIT_ID): cv.string,
        vol.Required(ATTR_VALUE): vol.Coerce(float),
    }
)

ACTIVATE_ROTATING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_CATEGORY): cv.string,
        vol.Optional(ATTR_QUARTER): vol.Match(r"^\d{4}-Q[1-4]$"),
    }
)


def _resolve_card(hass: HomeAssistant, device_id: str) -> tuple[CardPerksCoordinator, str]:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_device")
    held_card_id = next(
        (
            ident
            for dom, ident in device.identifiers
            if dom == DOMAIN and not ident.startswith("owner:")
        ),
        None,
    )
    if held_card_id is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_card_device")
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: CardPerksCoordinator = entry.runtime_data
        if held_card_id in coordinator.cards:
            return coordinator, held_card_id
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_card")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_sub_spend(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.add_sub_spend(
            card_id, call.data[ATTR_AMOUNT], call.data.get(ATTR_DATE), call.data.get(ATTR_NOTE)
        )

    async def set_perk_value(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.set_perk_value(card_id, call.data[ATTR_BENEFIT_ID], call.data[ATTR_VALUE])

    async def activate_rotating_category(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.activate_rotating_category(
            card_id, call.data[ATTR_CATEGORY], call.data.get(ATTR_QUARTER)
        )

    async def import_cards(call: ServiceCall) -> ServiceResponse:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_set_up")
        entry = entries[0]
        catalog = await async_get_catalog(hass)
        # Suppress the per-subentry reload while importing; reload once at the end.
        hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
        try:
            result = await async_import_cards(hass, entry, catalog, call.data[ATTR_CSV])
        finally:
            hass.data[DOMAIN][DATA_IMPORTING] = False
        if result.created_owners or result.created_cards:
            await hass.config_entries.async_reload(entry.entry_id)
        return result.as_dict()

    hass.services.async_register(DOMAIN, SERVICE_ADD_SUB_SPEND, add_sub_spend, ADD_SUB_SPEND_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_CARDS,
        import_cards,
        IMPORT_CARDS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PERK_VALUE, set_perk_value, SET_PERK_VALUE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_ROTATING_CATEGORY,
        activate_rotating_category,
        ACTIVATE_ROTATING_SCHEMA,
    )
