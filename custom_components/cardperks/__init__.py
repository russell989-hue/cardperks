"""CardPerks: track credit-card benefits so none go unused."""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_COLOR,
    DATA_IMPORTING,
    DOMAIN,
    ROLLOVER_HOUR,
    ROLLOVER_MINUTE,
    SUBENTRY_CARD,
)
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .devices import async_cleanup_entities, async_ensure_devices
from .helpers import async_load_catalog
from .repairs import async_check_catalog_issues
from .services import async_setup_services
from .store import CardPerksStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


OLD_SEPARATOR = " ·"
NEW_SEPARATOR = " | "


@callback
def _migrate_card_titles(hass: HomeAssistant, entry: CardPerksConfigEntry) -> int:
    """Rewrite card titles that still use the old last-four separator.

    Titles are shown as device names, so this keeps existing cards consistent with
    newly added ones without asking anyone to rename nine devices by hand.
    """
    changed = 0
    hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
    try:
        for sub in list(entry.subentries.values()):
            if sub.subentry_type == SUBENTRY_CARD and OLD_SEPARATOR in sub.title:
                hass.config_entries.async_update_subentry(
                    entry, sub, title=sub.title.replace(OLD_SEPARATOR, NEW_SEPARATOR)
                )
                changed += 1
    finally:
        hass.data[DOMAIN][DATA_IMPORTING] = False
    return changed


@callback
def _migrate_colors_to_config(hass: HomeAssistant, entry: CardPerksConfigEntry, doc) -> int:
    """Colours once chosen through a dropdown entity now live in the card form."""
    if not doc.card_colors:
        return 0
    moved = 0
    hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
    try:
        for card_id, color in list(doc.card_colors.items()):
            sub = entry.subentries.get(card_id)
            if sub is None or sub.subentry_type != SUBENTRY_CARD:
                continue
            if not sub.data.get(CONF_COLOR):
                hass.config_entries.async_update_subentry(
                    entry, sub, data={**sub.data, CONF_COLOR: color}
                )
                moved += 1
    finally:
        hass.data[DOMAIN][DATA_IMPORTING] = False
    doc.card_colors.clear()
    return moved


async def async_setup_entry(hass: HomeAssistant, entry: CardPerksConfigEntry) -> bool:
    if renamed := _migrate_card_titles(hass, entry):
        _LOGGER.debug("Renamed %s card titles to the new separator", renamed)

    catalog, problems = await async_load_catalog(hass)
    async_check_catalog_issues(hass, catalog, problems)

    store = CardPerksStore(hass)
    doc = await store.async_load_document()
    if moved := _migrate_colors_to_config(hass, entry, doc):
        _LOGGER.debug("Moved %s card colours into the card configuration", moved)
    coordinator = CardPerksCoordinator(hass, entry, catalog, store, doc)
    await coordinator.async_run_rollover()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_ensure_devices(hass, entry, coordinator)

    removed = async_cleanup_entities(hass, entry, coordinator)
    if removed:
        _LOGGER.debug("Removed %s stale entities after a catalog or card change", removed)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _scheduled_rollover(_now) -> None:
        hass.async_create_task(coordinator.async_run_rollover())
        async_check_catalog_issues(hass, coordinator.catalog, problems)

    entry.async_on_unload(
        async_track_time_change(
            hass, _scheduled_rollover, hour=ROLLOVER_HOUR, minute=ROLLOVER_MINUTE, second=0
        )
    )
    # Subentry add/update/remove does not reload the entry by itself.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: CardPerksConfigEntry) -> None:
    if hass.data.get(DOMAIN, {}).get(DATA_IMPORTING):
        return  # the import service reloads once when it finishes
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CardPerksConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save_document(entry.runtime_data.doc)
    return unloaded
