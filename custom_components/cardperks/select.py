"""Benefit status select entities and the entity services that act on them."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_AMOUNT,
    ATTR_DATE,
    ATTR_NOTE,
    SERVICE_MARK_USED,
    SERVICE_RESET_BENEFIT,
    SUBENTRY_CARD,
    BenefitStatus,
)
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import BenefitEntity
from .helpers import card_from_subentry
from .models import Benefit, HeldCard

STATUS_OPTIONS = [str(s) for s in BenefitStatus]


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
                BenefitStatusSelect(coordinator, card, benefit)
                for benefit in product.benefits_for_role(card.role)
            ],
            config_subentry_id=sub.subentry_id,
        )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_MARK_USED,
        {
            vol.Optional(ATTR_AMOUNT): vol.Coerce(float),
            vol.Optional(ATTR_DATE): cv.date,
            vol.Optional(ATTR_NOTE): cv.string,
        },
        "async_mark_used",
    )
    platform.async_register_entity_service(SERVICE_RESET_BENEFIT, None, "async_reset_benefit")


class BenefitStatusSelect(BenefitEntity, SelectEntity):
    _attr_translation_key = "benefit_status"
    _attr_options = STATUS_OPTIONS
    _attr_icon = "mdi:gift-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_status"

    @property
    def current_option(self) -> str | None:
        inst = self.instance
        return str(inst.status) if inst else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inst = self.instance
        if inst is None:
            return {}
        return {
            "benefit_id": self.benefit_id,
            "benefit_type": str(self.benefit.type),
            "cadence": str(self.benefit.cadence),
            "amount": inst.amount,
            "amount_used": inst.amount_used,
            "remaining": max((inst.amount or 0.0) - inst.amount_used, 0.0),
            "period_start": inst.period_start,
            "period_end": inst.period_end,
            "enrollment_required": self.benefit.enrollment_required,
            "uses": [u.to_dict() for u in inst.uses],
        }

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_status(self.held_card_id, self.benefit_id, BenefitStatus(option))

    async def async_mark_used(
        self, amount: float | None = None, date: date | None = None, note: str | None = None
    ) -> None:
        self.coordinator.mark_used(self.held_card_id, self.benefit_id, amount, date, note)

    async def async_reset_benefit(self) -> None:
        self.coordinator.reset_benefit(self.held_card_id, self.benefit_id)
