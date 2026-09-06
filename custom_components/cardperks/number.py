"""Dollar inputs: how much of a benefit you have used, and what a perk is worth to you.

Dollars are the point. A $25 monthly credit is $300 a year, and knowing you captured
$10 of this month's is far more useful than knowing it is "partially used", so the
amount is what you type and the status is derived from it.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

import voluptuous as vol
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
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
    BenefitType,
)
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
        entities: list[NumberEntity] = []
        for benefit in product.benefits_for(card):
            if benefit.is_dollar and not benefit.is_uncapped:
                entities.append(BenefitUsedNumber(coordinator, card, benefit))
            if benefit.type in VALUED_TYPES:
                entities.append(PerkValueNumber(coordinator, card, benefit))
        async_add_entities(entities, config_subentry_id=sub.subentry_id)

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


class BenefitUsedNumber(BenefitEntity, NumberEntity):
    """Dollars captured from this benefit in the current period."""

    _attr_translation_key = "benefit_used"
    _attr_device_class = NumberDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_step = 0.01
    _attr_icon = "mdi:cash-check"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_used"

    @property
    def native_max_value(self) -> float:
        inst = self.instance
        return float(inst.amount) if inst and inst.amount else 100000.0

    @property
    def native_value(self) -> float | None:
        inst = self.instance
        return None if inst is None else round(inst.amount_used, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inst = self.instance
        if inst is None:
            return {}
        summary = self.summary
        totals = summary.benefit_totals.get(self.benefit_id) if summary else None
        total = inst.amount
        out: dict[str, Any] = {
            **self.card_attributes,
            "benefit": self.benefit.name,
            "benefit_id": self.benefit_id,
            "status": str(inst.status),
            "this_period": total,
            "remaining": round(max((total or 0.0) - inst.amount_used, 0.0), 2),
            "percent_used": round(inst.amount_used / total * 100, 1) if total else None,
            "cadence": str(self.benefit.cadence),
            "periods_per_year": self.benefit.periods_per_year,
            "period_start": inst.period_start,
            "period_end": inst.period_end,
            "enrollment_required": self.benefit.enrollment_required,
            "uses": [u.to_dict() for u in inst.uses],
        }
        if totals is not None:
            out.update(totals.as_dict())
        return out

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_used(self.held_card_id, self.benefit_id, value)

    async def async_mark_used(
        self, amount: float | None = None, date: date_type | None = None, note: str | None = None
    ) -> None:
        self.coordinator.mark_used(self.held_card_id, self.benefit_id, amount, date, note)

    async def async_reset_benefit(self) -> None:
        self.coordinator.reset_benefit(self.held_card_id, self.benefit_id)


class PerkValueNumber(BenefitEntity, NumberEntity):
    """What a perk with no issuer dollar amount is worth to this cardholder."""

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
            **self.card_attributes,
            "benefit": self.benefit.name,
            "benefit_id": self.benefit_id,
            "catalog_default": self.benefit.default_value,
            "kind": "perk_value",  # stable hook for dashboard filters
            "customised": override is not None,
            "notes": self.benefit.notes,
        }

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_perk_value(self.held_card_id, self.benefit_id, value)


def _unused(status: BenefitStatus) -> bool:  # kept for readability in tests
    return status is BenefitStatus.UNUSED
