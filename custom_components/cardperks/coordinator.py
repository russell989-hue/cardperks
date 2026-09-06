"""Coordinator: single source of truth for CardPerks state."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CARD_COLORS,
    DOMAIN,
    FEE_WARNING_DAYS,
    BenefitStatus,
    BenefitType,
    CardStatus,
    Role,
)
from .helpers import cards_from_entry, now_iso, owners_from_entry, today_local
from .models import (
    Benefit,
    BenefitInstance,
    CardPerksData,
    CardSummary,
    Catalog,
    ExpiringItem,
    HeldCard,
    HistoryRecord,
    ImportRecord,
    OwnerSummary,
    StateDocument,
    SubTracker,
    Totals,
    UsageEvent,
    instance_key,
)
from .periods import add_months, compute_period, next_fee_date
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
        self.cards = self._cards_with_status(cards_from_entry(entry))

    def _cards_with_status(self, cards: dict[str, HeldCard]) -> dict[str, HeldCard]:
        out = {}
        for card_id, card in cards.items():
            raw = self.doc.card_status.get(card_id, CardStatus.ACTIVE)
            try:
                status = CardStatus(raw)
            except ValueError:
                status = CardStatus.ACTIVE
            out[card_id] = replace(card, status=status)
        return out

    def set_card_status(self, held_card_id: str, status: str) -> None:
        """Active, frozen or cancelled. Freezing closes the open periods."""
        self.card(held_card_id)
        try:
            new = CardStatus(status)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_status",
                translation_placeholders={"status": status},
            ) from err
        self.doc.card_status[held_card_id] = str(new)
        self.cards = self._cards_with_status(cards_from_entry(self.config_entry))
        rollover(self.doc, self.cards.values(), self.catalog, today_local(), now_iso())
        self._commit()

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

    def set_used(self, held_card_id: str, benefit_id: str, amount: float) -> None:
        """Set dollars used for the current period. The status follows from the number."""
        inst = self._require_instance(held_card_id, benefit_id)
        total = inst.amount
        amount = max(0.0, round(float(amount), 2))
        if total is not None:
            amount = min(amount, float(total))
        inst.amount_used = amount
        if amount <= 0:
            inst.status = BenefitStatus.UNUSED
            inst.uses = []
        elif total is None or total <= 0 or amount >= total:
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

    def record_import(
        self,
        held_card_id: str,
        *,
        file_hash: str,
        filename: str | None,
        issuer: str,
        months: set[str],
        first_date: str | None,
        last_date: str | None,
        rows: int,
        credit_rows: int,
        matched: int,
        applied: float,
    ) -> str:
        """Log a statement upload and mark the months it vouches for. Does not commit."""
        import_id = f"{file_hash[:12]}-{held_card_id[:8]}"
        self.doc.imports = [i for i in self.doc.imports if i.id != import_id]
        self.doc.imports.append(
            ImportRecord(
                id=import_id,
                file_hash=file_hash,
                filename=filename,
                issuer=issuer,
                held_card_id=held_card_id,
                imported_at=now_iso(),
                first_date=first_date,
                last_date=last_date,
                rows=rows,
                credit_rows=credit_rows,
                matched=matched,
                applied=round(applied, 2),
            )
        )
        covered = self.doc.coverage.setdefault(held_card_id, {})
        for month in months:
            covered[month] = import_id
        return import_id

    def coverage_months(self, held_card_id: str) -> set[str]:
        return set(self.doc.coverage.get(held_card_id, {}))

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

    def record_statement_usage(
        self,
        held_card_id: str,
        benefit_id: str,
        on: date,
        amount: float,
        note: str | None = None,
    ) -> bool:
        """Record a credit seen on a statement into the period it belongs to.

        Returns False if this exact event was already imported. Does not commit.
        """
        ref = f"{held_card_id}:{benefit_id}:{on.isoformat()}:{amount:.2f}:{note or ''}"
        if ref in self.doc.imported_refs:
            return False
        card = self.card(held_card_id)
        benefit = self.benefit(card, benefit_id)
        period = compute_period(
            on,
            benefit.cadence,
            benefit.reset,
            card.open_date,
            card.fee_month,
            benefit.expires_days_after_open,
        )
        if period is None:
            return False
        inst = self.instance(held_card_id, benefit_id)
        if inst is not None and inst.period_start == period.start.isoformat():
            inst.uses.append(UsageEvent(date=on.isoformat(), amount=amount, note=note))
            inst.amount_used = round(inst.amount_used + amount, 2)
            total = inst.amount
            inst.status = (
                BenefitStatus.USED
                if total is None or total <= 0 or inst.amount_used >= total
                else BenefitStatus.PARTIAL
            )
            inst.sticky_na = False
            inst.updated_at = now_iso()
        else:
            total = benefit.value(self.doc.perk_values.get(held_card_id, {}).get(benefit_id))
            rec = next(
                (
                    h
                    for h in self.doc.history
                    if h.held_card_id == held_card_id
                    and h.benefit_id == benefit_id
                    and h.period_start == period.start.isoformat()
                ),
                None,
            )
            if rec is None:
                rec = HistoryRecord(
                    held_card_id=held_card_id,
                    benefit_id=benefit_id,
                    period_start=period.start.isoformat(),
                    period_end=period.end.isoformat() if period.end else None,
                    final_status="unused",
                    amount=total or None,
                    amount_used=0.0,
                    closed_at=now_iso(),
                    closed_by="statement",
                )
                self.doc.history.append(rec)
            rec.amount_used = round(rec.amount_used + amount, 2)
            rec.final_status = str(
                BenefitStatus.USED
                if not total or rec.amount_used >= total
                else BenefitStatus.PARTIAL
            )
        self.doc.imported_refs.add(ref)
        return True

    def commit(self) -> None:
        """Persist and publish after a batch of mutations."""
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
            colors=self._colors(),
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

    def _colors(self) -> dict[str, str]:
        """A distinct colour per card so one card reads the same across every dashboard.

        The card form is the one place to choose it. Unchosen cards take a stable slot
        from the palette: cards are ordered by id, which is creation-ordered, so adding
        one appends rather than reshuffling what is already on screen.
        """
        out: dict[str, str] = {}
        for i, card_id in enumerate(sorted(self.cards)):
            out[card_id] = self.cards[card_id].color or CARD_COLORS[i % len(CARD_COLORS)]
        return out

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
        cutoff = today - timedelta(days=365)
        perks = self.doc.perk_values.get(card.id, {})

        # Per benefit: what a year of it is worth, and what became of the last twelve months.
        per_benefit: dict[str, Totals] = {}
        if product is not None and card.is_active(today):
            for benefit in product.benefits_for(card):
                if not benefit.is_dollar or benefit.id in card.not_applicable:
                    continue
                per_benefit[benefit.id] = Totals(
                    annual_value=benefit.annual_value(perks.get(benefit.id))
                )

        def bump(benefit_id: str, **deltas: float) -> None:
            cur = per_benefit.get(benefit_id)
            if cur is None:
                return
            per_benefit[benefit_id] = cur.plus(Totals(**deltas))

        for inst in self.doc.instances.values():
            if inst.held_card_id != card.id:
                continue
            amount = inst.amount or 0.0
            remaining = max(amount - inst.amount_used, 0.0)
            if inst.status in (BenefitStatus.UNUSED, BenefitStatus.PARTIAL) and remaining > 0:
                unused += remaining
                bump(inst.benefit_id, open_remaining=remaining)
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
            bump(inst.benefit_id, captured=inst.amount_used)

        for h in self.doc.history:
            if h.held_card_id != card.id:
                continue
            end = date.fromisoformat(h.period_end or h.period_start)
            if end < cutoff:
                continue
            bump(h.benefit_id, captured=h.amount_used)
            missed = max((h.amount or 0.0) - h.amount_used, 0.0)
            if not missed:
                continue
            if h.final_status == "unknown":
                bump(h.benefit_id, unknown=missed)
            elif h.final_status != str(BenefitStatus.NA):
                bump(h.benefit_id, forfeited=missed)

        totals = Totals()
        for t in per_benefit.values():
            totals = totals.plus(t)

        expiring.sort(key=lambda e: e.period_end)
        return CardSummary(
            held_card_id=card.id,
            fee_due=fee_due,
            fee_within_warning=fee_within,
            annual_fee=annual_fee,
            unused_value=round(unused, 2),
            used_value_12m=totals.captured,
            net_value_12m=round(totals.captured - annual_fee, 2),
            expiring=tuple(expiring),
            totals=totals,
            benefit_totals=per_benefit,
        )

    def _owner_summary(
        self, owner_id: str, card_summaries: dict[str, CardSummary], today: date
    ) -> OwnerSummary:
        unused = 0.0
        exp7: list[ExpiringItem] = []
        exp30: list[ExpiringItem] = []
        five24: list[str] = []
        totals = Totals()
        fees = 0.0
        window = add_months(today, -24)
        for card in self.cards.values():
            if card.owner_id != owner_id or not card.is_active(today):
                continue
            summary = card_summaries[card.id]
            unused += summary.unused_value
            totals = totals.plus(summary.totals)
            fees += summary.annual_fee
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
            totals=totals,
            annual_fees=round(fees, 2),
            unused_credits=round(unused, 2),
            expiring_7d=tuple(exp7),
            expiring_30d=tuple(exp30),
            five_24=len(five24),
            five_24_items=tuple(five24),
        )
