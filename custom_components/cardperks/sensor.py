"""Sensors: benefit expiry dates, card money views, owner rollups."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    STATUS_WARNING_DAYS,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
    BenefitStatus,
)
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import BenefitEntity, CardEntity, CardPerksEntity, OwnerEntity, owner_device_info
from .helpers import card_from_subentry, owner_from_subentry, today_local
from .models import Benefit, ExpiringItem, HeldCard, LoyaltyStatus, Owner


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
                CardLedgerSensor(coordinator, card),
            ]
            for b in product.benefits_for(card):
                if not b.is_uncapped:
                    entities.append(BenefitExpiresSensor(coordinator, card, b))
                    entities.append(BenefitRemainingSensor(coordinator, card, b))
                entities.append(BenefitStatusSensor(coordinator, card, b))
            async_add_entities(entities, config_subentry_id=sub.subentry_id)

    # Elite status: one sensor each, on the owner's device and under the owner's
    # subentry (a device belongs to one subentry). Card-granted ones vanish with the
    # card; entered ones are cleaned up when their subentry is removed.
    statuses = coordinator.statuses(today_local())
    for sid, status in statuses.items():
        owner = coordinator.owners.get(status.owner_id)
        if owner is None or status.owner_id not in entry.subentries:
            continue
        async_add_entities(
            [StatusSensor(coordinator, owner, sid)], config_subentry_id=status.owner_id
        )


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
            "benefit": self.benefit.label,
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
            "benefit": self.benefit.label,
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
            "benefit": self.benefit.label,
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
            "years": [y.as_dict() for y in s.years] if s else [],
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


class CardLedgerSensor(CardEntity, SensorEntity):
    """Every dollar logged against this card's benefits: the state counts the last
    twelve months' entries, the attributes carry the lines, newest first."""

    _attr_translation_key = "ledger"
    _attr_native_unit_of_measurement = "entries"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:notebook-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_ledger"

    @property
    def native_value(self) -> int:
        cutoff = (self.coordinator.data.today - timedelta(days=365)).isoformat()
        return sum(
            1
            for r in self.coordinator.doc.ledger
            if r["card_id"] == self.held_card_id and r["on"] >= cutoff
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rows = self.coordinator.ledger_for(self.held_card_id)
        return {
            **self.card_attributes,
            "entries": [
                {
                    "on": r["on"],
                    "benefit": r["benefit"],
                    "amount": r["amount"],
                    "source": r["source"],
                    "note": r.get("note"),
                }
                for r in rows
            ],
            "total_12m": round(
                sum(
                    r["amount"]
                    for r in rows
                    if r["on"] >= (self.coordinator.data.today - timedelta(days=365)).isoformat()
                ),
                2,
            ),
            "totals": self.coordinator.ledger_totals(
                self.held_card_id, self.coordinator.data.today
            ),
            "window": self.coordinator.doc.ledger_window,
        }


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
        names = {b.id: b.label for b in product.benefits} if product else {}
        worst = sorted(
            (t.forfeited, names.get(bid, bid)) for bid, t in s.benefit_totals.items() if t.forfeited
        )
        return {
            **self.card_attributes,
            "annual_value": s.totals.annual_value,
            "captured_12m": s.totals.captured,
            "forfeited_12m": s.totals.forfeited,
            "unknown_12m": s.totals.unknown,
            "open_remaining": s.totals.open_remaining,
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
            **self.owner_attributes,
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
            **self.owner_attributes,
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


class StatusSensor(CardPerksEntity, SensorEntity):
    """One elite status: the tier as state, with who holds it, where it comes from, and
    when it lapses. Card-granted statuses renew with the card's anniversary."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:medal-outline"

    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner, status_id: str) -> None:
        super().__init__(coordinator)
        self.status_id = status_id
        self._attr_unique_id = f"status_{status_id}"
        self._attr_device_info = owner_device_info(owner)
        st = coordinator.data.statuses.get(status_id)
        self._attr_translation_placeholders = {"program": st.program if st else status_id}

    @property
    def status(self) -> LoyaltyStatus | None:
        return self.coordinator.data.statuses.get(self.status_id)

    @property
    def available(self) -> bool:
        return super().available and self.status is not None

    @property
    def native_value(self) -> str | None:
        st = self.status
        return st.tier if st else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self.status
        if st is None:
            return {}
        data = self.coordinator.data
        owner = data.owners.get(st.owner_id)
        card = data.cards.get(st.card_id) if st.card_id else None
        days = (st.valid_through - data.today).days if st.valid_through else None
        out: dict[str, Any] = {
            "kind": self.translation_key,
            "program": st.program,
            "tier": st.tier,
            "owner": owner.name if owner else None,
            "owner_id": st.owner_id,
            "source": st.source,
            "card": card.title if card else None,
            "card_id": st.card_id,
            "color": data.colors.get(st.card_id) if st.card_id else "grey",
            "card_status": "active",
            "from_card": st.card_id is not None,
            "valid_through": st.valid_through.isoformat() if st.valid_through else None,
            "days_left": days,
            "expiring_soon": days is not None and days <= STATUS_WARNING_DAYS,
            "notes": st.notes,
        }
        program = data.catalog.programs.get(st.program_id or "")
        if program is not None:
            tier = program.tier(st.tier_id)
            nxt = program.next_tier(st.tier_id)
            out.update(
                {
                    "program_id": program.id,
                    "program_kind": program.kind,
                    "tier_rank": tier.rank if tier else None,
                    "tier_benefits": list(tier.benefits) if tier else [],
                    "how_earned": tier.qualify if tier else None,
                    "next_tier": nxt.name if nxt else None,
                    "next_tier_qualify": nxt.qualify if nxt else None,
                    "qualification": program.qualification,
                }
            )
        return out
