"""CardPerks: track credit-card benefits so none go unused."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import ROLLOVER_HOUR, ROLLOVER_MINUTE
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .helpers import async_load_catalog
from .repairs import async_check_catalog_issues
from .services import async_setup_services
from .store import CardPerksStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CardPerksConfigEntry) -> bool:
    catalog, problems = await async_load_catalog(hass)
    async_check_catalog_issues(hass, catalog, problems)

    store = CardPerksStore(hass)
    doc = await store.async_load_document()
    coordinator = CardPerksCoordinator(hass, entry, catalog, store, doc)
    await coordinator.async_run_rollover()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

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
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CardPerksConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save_document(entry.runtime_data.doc)
    return unloaded
