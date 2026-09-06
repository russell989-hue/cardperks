"""Diagnostics with personal fields redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_LAST4, CONF_NAME, CONF_NICKNAME, CONF_NOTES
from .coordinator import CardPerksConfigEntry

TO_REDACT = {CONF_LAST4, CONF_NICKNAME, CONF_NOTES, CONF_NAME, "title", "note"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CardPerksConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    subentries = [
        {
            "subentry_id": sub.subentry_id,
            "subentry_type": sub.subentry_type,
            "title": sub.title,
            "data": dict(sub.data),
        }
        for sub in entry.subentries.values()
    ]
    return async_redact_data(
        {
            "entry": {"title": entry.title, "data": dict(entry.data)},
            "subentries": subentries,
            "state": coordinator.doc.to_dict(),
            "catalog_products": sorted(coordinator.catalog.products),
        },
        TO_REDACT,
    )
