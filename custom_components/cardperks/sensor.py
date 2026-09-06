"""Sensors: benefit expiry dates, card money views, owner rollups."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SUBENTRY_CARD, SUBENTRY_OWNER, BenefitStatus
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import BenefitEntity, CardEntity, OwnerEntity
from .helpers import card_from_subentry, owner_from_subentry
from .models import Benefit, ExpiringItem, HeldCard, Owner


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CardPerksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_OWNER:
            owner = owner_from_subentry(sub)
            async_add_entities(
                [
                    OwnerUnusedCreditsSensor(coordinator, owner),
                    OwnerExpiringSensor(coordinator, owner, 7),
                    OwnerExpiringSensor(coordinator, owner, 30),
                    OwnerFive24Sensor(coordinator, owner),
                ],
                config_subentry_id=sub.subentry_id,
            )
        elif sub.subentry_type == SUBENTRY_CARD:
            card = card_from_subentry(sub)
            product = coordinator.catalog.get(card.product_id)
            if product is None:
                continue
            entities: list[SensorEntity] = [
                CardFeeDueSensor(coordinator, card),
                CardUnusedValueSensor(coordinator, card),
                CardNetValue12mSensor(coordinator, card),
            ]
            for b in product.benefits_for(card):
                entities.append(BenefitExpiresSensor(coordinator, card, b))
                entities.append(BenefitRemainingSensor(coordinator, card, b))
            async_add_entities(entities, config_subentry_id=sub.subentry_id)


def _items(items: tuple[ExpiringItem, ...]) -> list[dict[str, Any]]:
    return [
        {
            "card": i.card_title,
            "benefit": i.benefit_name,
            "expires": i.period_end.isoformat(),
            "remaining": i.remaining,
        }
        for i in items
    ]


# ------------------------------------------------------------------ benefit


class BenefitRemainingSensor(BenefitEntity, SensorEntity):
    """Dollars left on this benefit for the current period."""

    _attr_translation_key = "benefit_remaining"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_remaining"

    @property
    def native_value(self) -> float | None:
        inst = self.instance
        if inst is None or inst.amount is None:
            return None
        if inst.status is BenefitStatus.NA:
            return 0.0
        return round(max(inst.amount - inst.amount_used, 0.0), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inst = self.instance
        if inst is None:
            return {}
        total = inst.amount
        pct = round(inst.amount_used / total * 100, 1) if total else None
        return {
            "status": str(inst.status),
            "amount": total,
            "amount_used": inst.amount_used,
            "percent_used": pct,
            "period_start": inst.period_start,
            "period_end": inst.period_end,
            "cadence": str(self.benefit.cadence),
            "uses": [u.to_dict() for u in inst.uses],
        }


class BenefitExpiresSensor(BenefitEntity, SensorEntity):
    _attr_translation_key = "benefit_expires"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_expires"

    @property
    def native_value(self) -> date | None:
        inst = self.instance
        if inst is None or not inst.period_end:
            return None
        return date.fromisoformat(inst.period_end)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inst = self.instance
        if inst is None:
            return {}
        days = None
        if inst.period_end:
            days = (date.fromisoformat(inst.period_end) - self.coordinator.data.today).days
        return {
            "status": str(inst.status),
            "amount": inst.amount,
            "amount_used": inst.amount_used,
            "period_start": inst.period_start,
            "days_left": days,
        }


# ------------------------------------------------------------------ card


class CardFeeDueSensor(CardEntity, SensorEntity):
    _attr_translation_key = "fee_due"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-cash"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_fee_due"

    @property
    def native_value(self) -> date | None:
        s = self.summary
        return s.fee_due if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        card = self.card
        return {
            "annual_fee": s.annual_fee if s else None,
            "open_date": card.open_date.isoformat() if card and card.open_date else None,
            "fee_month": card.fee_month if card else None,
            "role": str(card.role) if card else None,
        }


class CardUnusedValueSensor(CardEntity, SensorEntity):
    _attr_translation_key = "unused_value"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_unused_value"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.unused_value if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        data = self.coordinator.data
        return {
            "expiring": _items(s.expiring) if s else [],
            "rotating_activations": dict(data.rotating_activations.get(self.held_card_id, {})),
        }


class CardNetValue12mSensor(CardEntity, SensorEntity):
    _attr_translation_key = "net_value_12m"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_net_value_12m"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.net_value_12m if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        tracker = self.coordinator.data.sub_trackers.get(self.held_card_id)
        return {
            "used_value_12m": s.used_value_12m if s else None,
            "annual_fee": s.annual_fee if s else None,
            "sub_tracker": tracker.to_dict() if tracker else None,
        }


# ------------------------------------------------------------------ owner


class OwnerUnusedCreditsSensor(OwnerEntity, SensorEntity):
    _attr_translation_key = "unused_credits"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner) -> None:
        super().__init__(coordinator, owner)
        self._attr_unique_id = f"owner_{owner.id}_unused_credits"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.unused_credits if s else None


class OwnerExpiringSensor(OwnerEntity, SensorEntity):
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "benefits"

    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner, days: int) -> None:
        super().__init__(coordinator, owner)
        self.days = days
        self._attr_translation_key = f"expiring_{days}d"
        self._attr_unique_id = f"owner_{owner.id}_expiring_{days}d"

    @property
    def native_value(self) -> int | None:
        s = self.summary
        if s is None:
            return None
        return len(s.expiring_7d if self.days == 7 else s.expiring_30d)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        if s is None:
            return {}
        items = s.expiring_7d if self.days == 7 else s.expiring_30d
        return {
            "items": _items(items),
            "total_remaining": round(sum(i.remaining for i in items), 2),
        }


class OwnerFive24Sensor(OwnerEntity, SensorEntity):
    _attr_translation_key = "five_24"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "accounts"

    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner) -> None:
        super().__init__(coordinator, owner)
        self._attr_unique_id = f"owner_{owner.id}_5_24"

    @property
    def native_value(self) -> int | None:
        s = self.summary
        return s.five_24 if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        return {
            "accounts": list(s.five_24_items) if s else [],
            "under_5_24": (s.five_24 < 5) if s else None,
        }
