"""Persistence for CardPerks state via the Home Assistant Store helper."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_MINOR_VERSION, STORAGE_VERSION
from .models import StateDocument

SAVE_DELAY = 2


class CardPerksStore(Store[dict[str, Any]]):
    """Store subclass with a migration hook."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
            minor_version=STORAGE_MINOR_VERSION,
            atomic_writes=True,
        )

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        # No migrations yet. Future versions branch on (old_major_version, old_minor_version).
        return old_data

    async def async_load_document(self) -> StateDocument:
        raw = await self.async_load()
        return StateDocument.from_dict(raw)

    def async_schedule_save(self, doc: StateDocument) -> None:
        self.async_delay_save(doc.to_dict, SAVE_DELAY)

    async def async_save_document(self, doc: StateDocument) -> None:
        await self.async_save(doc.to_dict())
