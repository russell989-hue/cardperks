"""Binary sensors: annual fee due soon."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import FEE_WARNING_DAYS, SUBENTRY_CARD
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import CardEntity
from .helpers import card_from_subentry
from .models import HeldCard


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CardPerksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_CARD:
            continue
        card = card_from_subentry(sub)
        async_add_entities(
            [CardFeeWithinWarningBinarySensor(coordinator, card)],
            config_subentry_id=sub.subentry_id,
        )


class CardFeeWithinWarningBinarySensor(CardEntity, BinarySensorEntity):
    _attr_translation_key = "fee_within_45d"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_fee_within_45d"

    @property
    def is_on(self) -> bool | None:
        s = self.summary
        return s.fee_within_warning if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        return {
            "fee_due": s.fee_due.isoformat() if s and s.fee_due else None,
            "annual_fee": s.annual_fee if s else None,
            "warning_days": FEE_WARNING_DAYS,
        }
