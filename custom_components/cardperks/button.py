"""One-tap mark-used buttons."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SUBENTRY_CARD
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import BenefitEntity
from .helpers import card_from_subentry
from .models import Benefit, HeldCard


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
        product = coordinator.catalog.get(card.product_id)
        if product is None:
            continue
        async_add_entities(
            [
                BenefitMarkUsedButton(coordinator, card, benefit)
                for benefit in product.benefits_for(card)
                if not benefit.is_uncapped
            ],
            config_subentry_id=sub.subentry_id,
        )


class BenefitMarkUsedButton(BenefitEntity, ButtonEntity):
    _attr_translation_key = "benefit_mark_used"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {**self.card_attributes, "benefit": self.benefit.label}

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_mark_used"

    async def async_press(self) -> None:
        self.coordinator.mark_used(self.held_card_id, self.benefit_id)
