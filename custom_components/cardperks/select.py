"""The one thing that genuinely is a picklist: a card's colour.

Dollar amounts are typed, not chosen from a list, so the only select this integration
ships is the colour used to identify a card across every dashboard.
"""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CARD_COLORS, SUBENTRY_CARD
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
        async_add_entities(
            [CardColorSelect(coordinator, card_from_subentry(sub))],
            config_subentry_id=sub.subentry_id,
        )


class CardColorSelect(CardEntity, SelectEntity):
    _attr_translation_key = "card_color"
    _attr_options: ClassVar[list[str]] = list(CARD_COLORS)
    _attr_icon = "mdi:palette"
    _attr_entity_category = None

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_color"

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.colors.get(self.held_card_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self.card_attributes,
            "chosen": self.held_card_id in self.coordinator.doc.card_colors,
        }

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_card_color(self.held_card_id, option)
