"""Coordinator: single source of truth for CardPerks state."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, FEE_WARNING_DAYS, BenefitStatus, BenefitType, Role
from .helpers import cards_from_entry, now_iso, owners_from_entry, today_local
from .models import (
    Benefit,
    BenefitInstance,
    CardPerksData,
    CardSummary,
    Catalog,
    ExpiringItem,
    HeldCard,
    OwnerSummary,
    StateDocument,
    SubTracker,
    UsageEvent,
    instance_key,
)
from .periods import add_months, next_fee_date
from .rollover import RolloverResult, rollover
from .store import CardPerksStore

_LOGGER = logging.getLogger(__name__)

type CardPerksConfigEntry = ConfigEntry[CardPerksCoordinator]


class CardPerksCoordinator(DataUpdateCoordinator[CardPerksData]):
    """Holds the mutable state document and publishes immutable snapshots."""

    config_entry: CardPerksConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CardPerksConfigEntry,
        catalog: Catalog,
        store: CardPerksStore,
        doc: StateDocument,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.catalog = catalog
        self.store = store
        self.doc = doc
        self.owners = owners_from_entry(entry)
        self.cards = cards_from_entry(entry)

    # ------------------------------------------------------------------ lifecycle

    async def _async_update_data(self) -> CardPerksData:
        return self._build_snapshot()

    def _commit(self) -> None:
        self.store.async_schedule_save(self.doc)
        self.async_set_updated_data(self._build_snapshot())

    async def async_run_rollover(self) -> RolloverResult:
        result = rollover(self.doc, self.cards.values(), self.catalog, today_local(), now_iso())
        if result.changed:
            _LOGGER.debug("Rollover: %s", result)
            self._commit()
        return result

    # ------------------------------------------------------------------ lookups

    def card(self, held_card_id: str) -> HeldCard:
        try:
            return self.cards[held_card_id]
        except KeyError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_card"
            ) from err

    def benefit(self, card: HeldCard, benefit_id: str) -> Benefit:
        product = self.catalog.get(card.product_id)
        benefit = product.benefit(benefit_id) if product else None
        if benefit is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_benefit",
                translation_placeholders={"benefit_id": benefit_id},
            )
        return benefit

    def instance(self, held_card_id: str, benefit_id: str) -> BenefitInstance | None:
        return self.doc.instances.get(instance_key(held_card_id, benefit_id))

    def _require_instance(self, held_card_id: str, benefit_id: str) -> BenefitInstance:
        inst = self.instance(held_card_id, benefit_id)
        if inst is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_current_period",
                translation_placeholders={"benefit_id": benefit_id},
            )
        return inst

    # ------------------------------------------------------------------ mutations

    def mark_used(
        self,
        held_card_id: str,
        benefit_id: str,
        amount: float | None = None,
        on: date | None = None,
        note: str | None = None,
    ) -> None:
        inst = self._require_instance(held_card_id, benefit_id)
        total = inst.amount
        if amount is None:
            amount = max((total or 0.0) - inst.amount_used, 0.0) if total else 0.0
        inst.uses.append(
            UsageEvent(date=(on or today_local()).isoformat(), amount=amount, note=note)
        )
        inst.amount_used = round(inst.amount_used + amount, 2)
        if total is None or total <= 0 or inst.amount_used >= total:
            inst.status = BenefitStatus.USED
        else:
            inst.status = BenefitStatus.PARTIAL
        inst.sticky_na = False
        inst.updated_at = now_iso()
        self._commit()

    def set_status(self, held_card_id: str, benefit_id: str, status: BenefitStatus) -> None:
        inst = self._require_instance(held_card_id, benefit_id)
        if status is BenefitStatus.USED and inst.amount:
            inst.amount_used = float(inst.amount)
        elif status is BenefitStatus.UNUSED:
            inst.amount_used = 0.0
            inst.uses = []
        inst.status = status
        inst.sticky_na = status is BenefitStatus.NA
        inst.updated_at = now_iso()
        self._commit()

    def reset_benefit(self, held_card_id: str, benefit_id: str) -> None:
        self.set_status(held_card_id, benefit_id, BenefitStatus.UNUSED)

    def add_sub_spend(
        self, held_card_id: str, amount: float, on: date | None = None, note: str | None = None
    ) -> None:
        card = self.card(held_card_id)
        benefit = self.benefit(card, "sub")
        tracker = self.doc.sub_trackers.get(held_card_id)
        if tracker is None:
            inst = self.instance(held_card_id, "sub")
            tracker = SubTracker(
                required=float(benefit.spend_required or 0.0),
                deadline=inst.period_end if inst else None,
            )
            self.doc.sub_trackers[held_card_id] = tracker
        when = (on or today_local()).isoformat()
        tracker.entries.append(UsageEvent(date=when, amount=amount, note=note))
        tracker.spent = round(tracker.spent + amount, 2)
        if tracker.required and tracker.spent >= tracker.required and not tracker.completed:
            tracker.completed_on = when
            inst = self.instance(held_card_id, "sub")
            if inst is not None:
                inst.status = BenefitStatus.USED
                inst.updated_at = now_iso()
        self._commit()

    def set_perk_value(self, held_card_id: str, benefit_id: str, value: float) -> None:
        card = self.card(held_card_id)
        benefit = self.benefit(card, benefit_id)
        if benefit.type not in (BenefitType.PERK, BenefitType.INSURANCE):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_perk",
                translation_placeholders={"benefit_id": benefit_id},
            )
        self.doc.perk_values.setdefault(held_card_id, {})[benefit_id] = float(value)
        inst = self.instance(held_card_id, benefit_id)
        if inst is not None:
            inst.amount = float(value)
            if inst.status is BenefitStatus.USED:
                inst.amount_used = float(value)
        self._commit()

    def activate_rotating_category(
        self, held_card_id: str, category: str, quarter: str | None = None
    ) -> None:
        self.card(held_card_id)
        if quarter is None:
            t = today_local()
            quarter = f"{t.year}-Q{(t.month - 1) // 3 + 1}"
        self.doc.rotating_activations.setdefault(held_card_id, {})[quarter] = {
            "category": category,
            "activated_on": today_local().isoformat(),
        }
        self._commit()

    # ------------------------------------------------------------------ snapshot

    def _build_snapshot(self) -> CardPerksData:
        today = today_local()
        card_summaries = {cid: self._card_summary(card, today) for cid, card in self.cards.items()}
        owner_summaries = {
            oid: self._owner_summary(oid, card_summaries, today) for oid in self.owners
        }
        return CardPerksData(
            today=today,
            owners=dict(self.owners),
            cards=dict(self.cards),
            catalog=self.catalog,
            instances=dict(self.doc.instances),
            card_summaries=card_summaries,
            owner_summaries=owner_summaries,
            sub_trackers=dict(self.doc.sub_trackers),
            rotating_activations=dict(self.doc.rotating_activations),
            perk_values=dict(self.doc.perk_values),
        )

    def _card_summary(self, card: HeldCard, today: date) -> CardSummary:
        product = self.catalog.get(card.product_id)
        annual_fee = 0.0
        if card.annual_fee is not None:
            annual_fee = card.annual_fee
        elif product is not None:
            annual_fee = (
                product.au_terms.fee if card.role is Role.AUTHORIZED_USER else product.annual_fee
            )

        fee_due = (
            next_fee_date(today, card.open_date, card.fee_month) if card.is_active(today) else None
        )
        fee_within = fee_due is not None and (fee_due - today).days <= FEE_WARNING_DAYS

        unused = 0.0
        expiring: list[ExpiringItem] = []
        used_12m = 0.0
        cutoff = today - timedelta(days=365)

        for inst in self.doc.instances.values():
            if inst.held_card_id != card.id:
                continue
            amount = inst.amount or 0.0
            remaining = max(amount - inst.amount_used, 0.0)
            if inst.status in (BenefitStatus.UNUSED, BenefitStatus.PARTIAL) and remaining > 0:
                unused += remaining
                if inst.period_end:
                    benefit = product.benefit(inst.benefit_id) if product else None
                    expiring.append(
                        ExpiringItem(
                            held_card_id=card.id,
                            card_title=card.title,
                            benefit_id=inst.benefit_id,
                            benefit_name=benefit.name if benefit else inst.benefit_id,
                            period_end=date.fromisoformat(inst.period_end),
                            remaining=remaining,
                        )
                    )
            used_12m += inst.amount_used

        for h in self.doc.history:
            if h.held_card_id != card.id:
                continue
            end = date.fromisoformat(h.period_end or h.period_start)
            if end >= cutoff:
                used_12m += h.amount_used

        expiring.sort(key=lambda e: e.period_end)
        return CardSummary(
            held_card_id=card.id,
            fee_due=fee_due,
            fee_within_warning=fee_within,
            annual_fee=annual_fee,
            unused_value=round(unused, 2),
            used_value_12m=round(used_12m, 2),
            net_value_12m=round(used_12m - annual_fee, 2),
            expiring=tuple(expiring),
        )

    def _owner_summary(
        self, owner_id: str, card_summaries: dict[str, CardSummary], today: date
    ) -> OwnerSummary:
        unused = 0.0
        exp7: list[ExpiringItem] = []
        exp30: list[ExpiringItem] = []
        five24: list[str] = []
        window = add_months(today, -24)
        for card in self.cards.values():
            if card.owner_id != owner_id:
                continue
            summary = card_summaries[card.id]
            unused += summary.unused_value
            for item in summary.expiring:
                days = (item.period_end - today).days
                if days <= 7:
                    exp7.append(item)
                if days <= 30:
                    exp30.append(item)
            product = self.catalog.get(card.product_id)
            if (
                product is not None
                and product.reports_to_personal_credit
                and card.open_date is not None
                and card.open_date > window
            ):
                five24.append(card.title)
        exp7.sort(key=lambda e: e.period_end)
        exp30.sort(key=lambda e: e.period_end)
        return OwnerSummary(
            owner_id=owner_id,
            unused_credits=round(unused, 2),
            expiring_7d=tuple(exp7),
            expiring_30d=tuple(exp30),
            five_24=len(five24),
            five_24_items=tuple(five24),
        )
