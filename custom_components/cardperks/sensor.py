"""Sensors: benefit expiry dates, card money views, owner rollups."""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
                    OwnerTotalSensor(coordinator, owner, "annual_value"),
                    OwnerTotalSensor(coordinator, owner, "captured_12m"),
                    OwnerTotalSensor(coordinator, owner, "forfeited_12m"),
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
                CardTotalSensor(coordinator, card, "annual_value"),
                CardTotalSensor(coordinator, card, "captured_12m"),
                CardTotalSensor(coordinator, card, "forfeited_12m"),
                CardCaptureRateSensor(coordinator, card),
                CardCoverageSensor(coordinator, card),
            ]
            for b in product.benefits_for(card):
                if not b.is_uncapped:
                    entities.append(BenefitExpiresSensor(coordinator, card, b))
                    entities.append(BenefitRemainingSensor(coordinator, card, b))
                entities.append(BenefitStatusSensor(coordinator, card, b))
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
            **self.card_attributes,
            "benefit": self.benefit.name,
            "status": str(inst.status),
            "amount": total,
            "amount_used": inst.amount_used,
            "percent_used": pct,
            "period_start": inst.period_start,
            "period_end": inst.period_end,
            "cadence": str(self.benefit.cadence),
            "uses": [u.to_dict() for u in inst.uses],
        }


class BenefitStatusSensor(BenefitEntity, SensorEntity):
    """Derived from the dollars used. Read-only: the number box is the input."""

    _attr_translation_key = "benefit_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [str(s) for s in BenefitStatus]
    _attr_icon = "mdi:gift-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card, benefit)
        self._attr_unique_id = f"{card.id}_{benefit.id}_status"

    @property
    def native_value(self) -> str | None:
        inst = self.instance
        return str(inst.status) if inst else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        inst = self.instance
        if inst is None:
            return {}
        return {
            **self.card_attributes,
            "benefit": self.benefit.name,
            "benefit_id": self.benefit_id,
            "amount": inst.amount,
            "amount_used": inst.amount_used,
            "period_start": inst.period_start,
            "period_end": inst.period_end,
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
            **self.card_attributes,
            "benefit": self.benefit.name,
            "status": str(inst.status),
            "amount": inst.amount,
            "amount_used": inst.amount_used,
            "remaining": round(max((inst.amount or 0.0) - inst.amount_used, 0.0), 2),
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
            **self.card_attributes,
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
            **self.card_attributes,
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
            **self.card_attributes,
            "used_value_12m": s.used_value_12m if s else None,
            "annual_fee": s.annual_fee if s else None,
            "sub_tracker": tracker.to_dict() if tracker else None,
        }


class CardTotalSensor(CardEntity, SensorEntity):
    """Annual value, captured or forfeited over the trailing twelve months."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    _ICONS: ClassVar[dict[str, str]] = {
        "annual_value": "mdi:cash-100",
        "captured_12m": "mdi:cash-check",
        "forfeited_12m": "mdi:cash-remove",
    }

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, key: str) -> None:
        super().__init__(coordinator, card)
        self.key = key
        self._attr_translation_key = key
        self._attr_icon = self._ICONS[key]
        self._attr_unique_id = f"{card.id}_{key}"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.totals.as_dict()[self.key] if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        if s is None:
            return {}
        out = dict(s.totals.as_dict())
        out["annual_fee"] = s.annual_fee
        return {**out, **self.card_attributes}


class CardCoverageSensor(CardEntity, SensorEntity):
    """How many of the last twelve months a statement actually vouches for.

    Without this you cannot tell a benefit you genuinely let expire from one you simply
    never imported a statement for, and the forfeited figure would be a guess.
    """

    _attr_translation_key = "coverage_12m"
    _attr_native_unit_of_measurement = "months"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:file-document-check-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_coverage_12m"

    def _window(self) -> list[str]:
        today = self.coordinator.data.today
        months = []
        year, month = today.year, today.month
        for _ in range(12):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        return list(reversed(months))

    @property
    def native_value(self) -> int:
        covered = self.coordinator.coverage_months(self.held_card_id)
        return sum(1 for m in self._window() if m in covered)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        covered = self.coordinator.coverage_months(self.held_card_id)
        window = self._window()
        mine = [i for i in self.coordinator.doc.imports if i.held_card_id == self.held_card_id]
        mine.sort(key=lambda i: i.imported_at)
        return {
            **self.card_attributes,
            "covered": [m for m in window if m in covered],
            "missing": [m for m in window if m not in covered],
            "statements_imported": len(mine),
            "last_import": mine[-1].imported_at if mine else None,
            "last_file": mine[-1].filename if mine else None,
        }


class CardCaptureRateSensor(CardEntity, SensorEntity):
    """Share of this card's annual credit value actually captured."""

    _attr_translation_key = "capture_rate"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:percent-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_capture_rate"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.totals.capture_rate if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        if s is None:
            return {}
        product = self.coordinator.catalog.get(s and self.card.product_id) if self.card else None
        names = {b.id: b.name for b in product.benefits} if product else {}
        worst = sorted(
            (t.forfeited, names.get(bid, bid)) for bid, t in s.benefit_totals.items() if t.forfeited
        )
        return {
            **self.card_attributes,
            "annual_value": s.totals.annual_value,
            "captured_12m": s.totals.captured,
            "forfeited_12m": s.totals.forfeited,
            "worst_forfeited": [
                {"benefit": name, "forfeited": amt} for amt, name in reversed(worst[-5:])
            ],
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.owner_attributes)


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


class OwnerTotalSensor(OwnerEntity, SensorEntity):
    """Household-side annual value, captured or forfeited over twelve months."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    _ICONS: ClassVar[dict[str, str]] = {
        "annual_value": "mdi:cash-100",
        "captured_12m": "mdi:cash-check",
        "forfeited_12m": "mdi:cash-remove",
    }

    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner, key: str) -> None:
        super().__init__(coordinator, owner)
        self.key = key
        self._attr_translation_key = key
        self._attr_icon = self._ICONS[key]
        self._attr_unique_id = f"owner_{owner.id}_{key}"

    @property
    def native_value(self) -> float | None:
        s = self.summary
        return s.totals.as_dict()[self.key] if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.summary
        if s is None:
            return {}
        out = dict(s.totals.as_dict())
        out["annual_fees"] = s.annual_fees
        out["net_12m"] = round(s.totals.captured - s.annual_fees, 2)
        return {**out, **self.owner_attributes}
