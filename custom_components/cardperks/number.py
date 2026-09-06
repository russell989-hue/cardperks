"""Editable dollar value for perks and insurance benefits.

Statement credits carry a hard amount from the issuer. Perks (lounge access, elite
status, phone insurance) are worth whatever they are worth to you, so each one gets a
number entity you can type into, on the card's device page or a dashboard.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SUBENTRY_CARD, BenefitType
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import BenefitEntity
from .helpers import card_from_subentry
from .models import Benefit, HeldCard

VALUED_TYPES = (BenefitType.PERK, BenefitType.INSURANCE)


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
                PerkValueNumber(coordinator, card, benefit)
                for benefit in product.benefits_for(card)
                if benefit.type in VALUED_TYPES
            ],
            config_subentry_id=sub.subentry_id,
        )


class PerkValueNumber(BenefitEntity, NumberEntity):
    _attr_translation_key = "perk_value"
    _attr_device_class = NumberDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 1
    _attr_icon = "mdi:tag-text-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_value"

    @property
    def available(self) -> bool:
        # Unlike the other benefit entities this stays usable between periods.
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float:
        override = self.coordinator.data.perk_values.get(self.held_card_id, {}).get(self.benefit_id)
        return self.benefit.value(override)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        override = self.coordinator.data.perk_values.get(self.held_card_id, {}).get(self.benefit_id)
        return {
            "benefit_id": self.benefit_id,
            "catalog_default": self.benefit.default_value,
            "customised": override is not None,
            "notes": self.benefit.notes,
        }

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_perk_value(self.held_card_id, self.benefit_id, value)
