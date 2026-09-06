"""Coordinator: single source of truth for CardPerks state."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .const import (
    CARD_COLORS,
    DOMAIN,
    FEE_WARNING_DAYS,
    HISTORY_RETENTION_DAYS,
    STATEMENT_GRACE_MONTHS,
    BenefitStatus,
    BenefitType,
    CardStatus,
    LedgerWindow,
    Role,
)
from .helpers import (
    cards_from_entry,
    now_iso,
    owners_from_entry,
    statuses_from_entry,
    today_local,
)
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
    LoyaltyStatus,
    OwnerSummary,
    SharedPerk,
    StateDocument,
    SubTracker,
    Totals,
    UsageEvent,
    YearRecord,
    instance_key,
)
from .periods import add_months, compute_period, months_spanned, next_fee_date
from .rollover import RolloverResult, rollover
from .store import CardPerksStore

_LOGGER = logging.getLogger(__name__)

type CardPerksConfigEntry = ConfigEntry[CardPerksCoordinator]


def seed_shared_values(
    doc: StateDocument, members: Mapping[str, list[tuple[HeldCard, Benefit]]]
) -> int:
    """Carry per-card perk values over to the household number, once.

    Before shared perks existed, Priority Pass was valued on each card separately. A
    holder who typed a value on one card was pricing the membership, so when a shared
    key has no household value yet and any of its cards carries a typed value, the
    household number starts as the sum of the typed values (catalog defaults are not
    added in). Returns how many keys were seeded.
    """
    seeded = 0
    for key, pairs in members.items():
        if key in doc.shared_values:
            continue
        typed = [
            doc.perk_values[card.id][benefit.id]
            for card, benefit in pairs
            if benefit.id in doc.perk_values.get(card.id, {})
        ]
        if typed:
            doc.shared_values[key] = round(sum(typed), 2)
            seeded += 1
    return seeded


def seed_ledger(doc: StateDocument) -> int:
    """Build the ledger once from the statement lines already imported.

    Before the ledger existed, statement credits left only their dedupe keys behind
    (card:benefit:date:amount:note). Those are enough to reconstruct what a statement
    recorded and when; manual entries from before this point are gone for good.
    """
    if doc.ledger or not doc.imported_refs:
        return 0
    rows = []
    for ref in doc.imported_refs:
        parts = ref.split(":", 4)
        if len(parts) < 4:
            continue
        card_id, benefit_id, on, amount = parts[:4]
        note = parts[4] if len(parts) > 4 else ""
        try:
            rows.append(
                {
                    "at": f"{on}T00:00:00",
                    "on": on,
                    "card_id": card_id,
                    "benefit_id": benefit_id,
                    "amount": float(amount),
                    "source": "statement",
                    "note": note or None,
                }
            )
        except ValueError:
            continue
    rows.sort(key=lambda r: (r["on"], r["card_id"], r["benefit_id"]))
    doc.ledger = rows
    return len(rows)


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
        self.user_statuses = statuses_from_entry(entry)
        if seed_shared_values(self.doc, self.shared_members(today_local())):
            self.store.async_schedule_save(self.doc)
        if seed_ledger(self.doc):
            self.store.async_schedule_save(self.doc)

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
        today = today_local()
        rollover(
            self.doc,
            self.cards.values(),
            self.catalog,
            today,
            now_iso(),
            perk_values=self.effective_perk_values(today),
        )
        self._sync_shared_amounts(today)
        self._commit()

    # ------------------------------------------------------------------ lifecycle

    async def _async_update_data(self) -> CardPerksData:
        return self._build_snapshot()

    def _commit(self) -> None:
        self.store.async_schedule_save(self.doc)
        self.async_set_updated_data(self._build_snapshot())

    async def async_run_rollover(self) -> RolloverResult:
        today = today_local()
        result = rollover(
            self.doc,
            self.cards.values(),
            self.catalog,
            today,
            now_iso(),
            perk_values=self.effective_perk_values(today),
        )
        if self._sync_shared_amounts(today):
            result.changed = True
        if result.changed:
            _LOGGER.debug("Rollover: %s", result)
            self._commit()
        return result

    # ------------------------------------------------------------------ the ledger

    def _log(
        self,
        card_id: str,
        benefit_id: str,
        amount: float,
        source: str,
        on: date | None = None,
        note: str | None = None,
    ) -> None:
        """One ledger line. Negative amounts are corrections (a box set lower, a reset)."""
        if not amount:
            return
        self.doc.ledger.append(
            {
                "at": now_iso(),
                "on": (on or today_local()).isoformat(),
                "card_id": card_id,
                "benefit_id": benefit_id,
                "amount": round(float(amount), 2),
                "source": source,
                "note": note,
            }
        )

    @staticmethod
    def window_bounds(window: str, today: date) -> tuple[str, str]:
        """ISO start (inclusive) and end (exclusive) dates for a ledger window."""
        if window == LedgerWindow.YTD:
            return date(today.year, 1, 1).isoformat(), (today + timedelta(days=1)).isoformat()
        if window == LedgerWindow.PRIOR_YEAR:
            return date(today.year - 1, 1, 1).isoformat(), date(today.year, 1, 1).isoformat()
        if window == LedgerWindow.T12:
            return (today - timedelta(days=365)).isoformat(), (
                today + timedelta(days=1)
            ).isoformat()
        return "0000-00-00", "9999-12-31"

    def ledger_totals(self, card_id: str, today: date) -> dict[str, float]:
        """Dollars logged against the card in each window."""
        rows = [r for r in self.doc.ledger if r["card_id"] == card_id]
        out: dict[str, float] = {}
        for w in LedgerWindow:
            lo, hi = self.window_bounds(w, today)
            out[str(w)] = round(sum(r["amount"] for r in rows if lo <= r["on"] < hi), 2)
        return out

    def set_ledger_window(self, window: str) -> None:
        self.doc.ledger_window = str(LedgerWindow(window))
        self._commit()

    def ledger_for(self, card_id: str, limit: int = 200) -> list[dict]:
        """This card's ledger, newest first, with benefit names filled in."""
        card = self.cards.get(card_id)
        product = self.catalog.get(card.product_id) if card else None
        names = {b.id: b.label for b in product.benefits} if product else {}
        rows = [r for r in self.doc.ledger if r["card_id"] == card_id]
        # Newest first; entries logged the same second keep their order of entry.
        rows = [
            r
            for _, r in sorted(
                enumerate(rows), key=lambda t: (t[1]["on"], t[1]["at"], t[0]), reverse=True
            )
        ]
        return [{**r, "benefit": names.get(r["benefit_id"], r["benefit_id"])} for r in rows[:limit]]

    # ------------------------------------------------------------------ calendar reminders

    def add_reminder(self, day: date, summary: str, description: str | None) -> str:
        """A note on the CardPerks calendar, kept until it is deleted there."""
        uid = f"reminder-{uuid4().hex[:12]}"
        self.doc.reminders.append(
            {"uid": uid, "date": day.isoformat(), "summary": summary, "description": description}
        )
        self._commit()
        return uid

    def remove_reminder(self, uid: str) -> None:
        before = len(self.doc.reminders)
        self.doc.reminders = [r for r in self.doc.reminders if r["uid"] != uid]
        if len(self.doc.reminders) == before:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_reminder",
                translation_placeholders={"uid": uid},
            )
        self._commit()

    # ------------------------------------------------------------------ loyalty status

    def statuses(self, today: date) -> dict[str, LoyaltyStatus]:
        """Every elite status in the household: granted by a held card, or entered.

        A card-granted status lasts as long as the card is held, so its expiry is the
        card's next anniversary and it disappears when the card is frozen, cancelled or
        the benefit marked not applicable.
        """
        out: dict[str, LoyaltyStatus] = dict(self.user_statuses)
        for card in self.cards.values():
            if not card.is_active(today):
                continue
            product = self.catalog.get(card.product_id)
            if product is None:
                continue
            renews = next_fee_date(today, card.open_date, card.fee_month)
            for benefit in product.benefits_for(card):
                if benefit.id in card.not_applicable:
                    continue
                for grant in benefit.grants_status:
                    sid = f"card_{card.id}_{benefit.id}_{slugify(grant.program)}"
                    out[sid] = LoyaltyStatus(
                        id=sid,
                        owner_id=card.owner_id,
                        program=grant.program,
                        tier=grant.tier,
                        valid_through=renews,
                        source=card.title,
                        card_id=card.id,
                    )
        return out

    # ------------------------------------------------------------------ shared perks

    def shared_members(self, today: date) -> dict[str, list[tuple[HeldCard, Benefit]]]:
        """Active cards carrying each shared perk, by shared key."""
        out: dict[str, list[tuple[HeldCard, Benefit]]] = {}
        for card in self.cards.values():
            if not card.is_active(today):
                continue
            product = self.catalog.get(card.product_id)
            if product is None:
                continue
            for benefit in product.benefits_for(card):
                if benefit.shared_key and benefit.id not in card.not_applicable:
                    out.setdefault(benefit.shared_key, []).append((card, benefit))
        return out

    def shared_perks(self, today: date) -> dict[str, SharedPerk]:
        """Each shared perk's household value and its split across cards.

        Priority Pass on three cards is one membership, so it is worth one number to the
        household, and that number is divided equally between the cards that carry it.
        Freezing or cancelling a card moves its share to the others.
        """
        out: dict[str, SharedPerk] = {}
        for key, members in self.shared_members(today).items():
            default = next((b.default_value for _, b in members if b.default_value), None)
            override = self.doc.shared_values.get(key)
            total = float(override) if override is not None else float(default or 0.0)
            out[key] = SharedPerk(
                key=key,
                name=members[0][1].name,
                value=round(total, 2),
                per_card=round(total / len(members), 2),
                card_ids=tuple(card.id for card, _ in members),
                customised=override is not None,
                default=default,
            )
        return out

    def effective_perk_values(self, today: date) -> dict[str, dict[str, float]]:
        """Per-card perk values with each shared perk replaced by its share."""
        values = {cid: dict(v) for cid, v in self.doc.perk_values.items()}
        perks = self.shared_perks(today)
        for key, members in self.shared_members(today).items():
            for card, benefit in members:
                values.setdefault(card.id, {})[benefit.id] = perks[key].per_card
        return values

    def _sync_shared_amounts(self, today: date) -> bool:
        """Bring open instances of shared perks to the current split. Returns whether any moved."""
        changed = False
        perks = self.shared_perks(today)
        for key, members in self.shared_members(today).items():
            per = perks[key].per_card
            for card, benefit in members:
                inst = self.doc.instances.get(instance_key(card.id, benefit.id))
                if inst is None or inst.amount == per:
                    continue
                inst.amount = per
                if inst.status is BenefitStatus.USED:
                    inst.amount_used = per
                inst.updated_at = now_iso()
                changed = True
        return changed

    def set_shared_value(self, key: str, value: float) -> None:
        """What a shared perk is worth to the household, all cards together."""
        today = today_local()
        if key not in self.shared_members(today):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_shared",
                translation_placeholders={"key": key},
            )
        self.doc.shared_values[key] = float(value)
        self._sync_shared_amounts(today)
        self._commit()

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
        self._log(held_card_id, benefit_id, amount, "manual", on, note)
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
        self._log(held_card_id, benefit_id, round(amount - inst.amount_used, 2), "manual")
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
            self._log(
                held_card_id, benefit_id, round(float(inst.amount) - inst.amount_used, 2), "manual"
            )
            inst.amount_used = float(inst.amount)
        elif status is BenefitStatus.UNUSED:
            self._log(held_card_id, benefit_id, -inst.amount_used, "manual", note="reset")
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
        # One receipt per (file, card): the same export re-imported replaces its record.
        import_id = f"{file_hash[:12]}-{held_card_id}"
        self.doc.imports = [
            i
            for i in self.doc.imports
            if not (i.file_hash == file_hash and i.held_card_id == held_card_id)
        ]
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
        if benefit.shared_key:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="shared_perk",
                translation_placeholders={"benefit_id": benefit_id, "key": benefit.shared_key},
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
        self._log(held_card_id, benefit_id, amount, "statement", on, note)
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
        perk_values = self.effective_perk_values(today)
        card_summaries = {
            cid: self._card_summary(card, today, perk_values.get(cid, {}))
            for cid, card in self.cards.items()
        }
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
            perk_values=perk_values,
            shared_perks=self.shared_perks(today),
            statuses=self.statuses(today),
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

    @staticmethod
    def _card_fee(card: HeldCard, product) -> float:
        """The fee the card carries today: the holder's override, else the catalog's."""
        if card.annual_fee is not None:
            return float(card.annual_fee)
        if product is None:
            return 0.0
        return float(
            product.au_terms.fee if card.role is Role.AUTHORIZED_USER else product.annual_fee
        )

    def _card_summary(
        self, card: HeldCard, today: date, perks: Mapping[str, float] | None = None
    ) -> CardSummary:
        product = self.catalog.get(card.product_id)
        annual_fee = self._card_fee(card, product)

        fee_due = (
            next_fee_date(today, card.open_date, card.fee_month) if card.is_active(today) else None
        )
        fee_within = fee_due is not None and (fee_due - today).days <= FEE_WARNING_DAYS

        unused = 0.0
        expiring: list[ExpiringItem] = []
        cutoff = today - timedelta(days=365)
        if perks is None:
            perks = self.effective_perk_values(today).get(card.id, {})

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
                            benefit_name=benefit.label if benefit else inst.benefit_id,
                            period_end=date.fromisoformat(inst.period_end),
                            remaining=remaining,
                        )
                    )
            bump(inst.benefit_id, captured=inst.amount_used)

        # Statements are the evidence for statement credits. Once a card has had any
        # imported, a closed credit period is only "forfeited" when a statement covered
        # every month of it; a month nobody has a statement for is unknown, not lost.
        # Perks and insurance never show on a statement, so they keep the manual rule,
        # as does a card that is tracked by hand and has no statements at all.
        covered = self.coverage_months(card.id)

        def vouched_for(h: HistoryRecord) -> bool:
            if not covered:
                return True
            benefit = product.benefit(h.benefit_id) if product else None
            if benefit is None or benefit.type is not BenefitType.STATEMENT_CREDIT:
                return True
            start = date.fromisoformat(h.period_start)
            end = date.fromisoformat(h.period_end) if h.period_end else None
            return all(m in covered for m in months_spanned(start, end))

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
            if h.final_status == str(BenefitStatus.NA):
                continue
            if h.final_status == "unknown" or not vouched_for(h):
                bump(h.benefit_id, unknown=missed)
            else:
                bump(h.benefit_id, forfeited=missed)

        # A rebate has no pool to capture from, so its annual value is what it returned;
        # that keeps the capture rate honest instead of inflating it with free money.
        if product is not None:
            for benefit in product.benefits_for(card):
                if benefit.is_uncapped and benefit.id in per_benefit:
                    t = per_benefit[benefit.id]
                    per_benefit[benefit.id] = replace(t, annual_value=t.captured)

        totals = Totals()
        for t in per_benefit.values():
            totals = totals.plus(t)

        expiring.sort(key=lambda e: e.period_end)
        freshness = self._statement_freshness(card, covered, today)
        years = self.card_years(card, today, covered)
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
            years=years,
            **freshness,
        )

    def card_years(self, card: HeldCard, today: date, covered: set[str]) -> tuple[YearRecord, ...]:
        """The card's cardmember years, newest first, from what statements prove.

        Anchored on the anniversary (fee month or open date). A year is listed when
        something is known about it: a fee line, a recorded credit, or a covered month.
        The current year is always listed. Nothing is claimed about what was available.

        The fee is the statement's fee line for that year when one was imported; failing
        that, the card's fee today, marked as an estimate. Credits count what statements
        and the holder recorded; perks count only when the holder marked them used, at
        the value the holder gave them.
        """
        nxt = next_fee_date(today, card.open_date, card.fee_month)
        if nxt is None:
            return ()
        fees = self.doc.fees_seen.get(card.id, {})
        product = self.catalog.get(card.product_id)
        perk_ids = {
            b.id
            for b in (product.benefits if product else ())
            if b.type in (BenefitType.PERK, BenefitType.INSURANCE)
        }
        summary_fee = self._card_fee(card, product)
        oldest = today - timedelta(days=HISTORY_RETENTION_DAYS)
        out: list[YearRecord] = []
        start = add_months(nxt, -12)
        while start >= oldest:
            end = add_months(start, 12) - timedelta(days=1)
            s_iso, e_iso = start.isoformat(), end.isoformat()
            captured = perks = 0.0
            for h in self.doc.history:
                if h.held_card_id == card.id and s_iso <= h.period_start <= e_iso:
                    if h.benefit_id in perk_ids:
                        perks += h.amount_used
                    else:
                        captured += h.amount_used
            for i in self.doc.instances.values():
                if i.held_card_id == card.id and s_iso <= i.period_start <= e_iso:
                    if i.benefit_id in perk_ids:
                        perks += i.amount_used
                    else:
                        captured += i.amount_used
            fee_total = [amt for d, amt in fees.items() if s_iso <= d <= e_iso]
            months = [
                m for m in months_spanned(start, min(end, today)) if m <= today.strftime("%Y-%m")
            ]
            covered_here = sum(1 for m in months if m in covered)
            current = start <= today <= end
            if current or fee_total or captured or perks or covered_here:
                if fee_total:
                    fee, source = round(sum(fee_total), 2), "statement"
                elif product is not None:
                    fee, source = summary_fee, "estimate"  # a $0 fee is still a fee
                else:
                    fee, source = None, "none"
                out.append(
                    YearRecord(
                        start=start,
                        end=end,
                        fee=fee,
                        captured=round(captured, 2),
                        months_covered=covered_here,
                        months=len(months),
                        current=current,
                        fee_source=source,
                        perks_value=round(perks, 2),
                    )
                )
            start = add_months(start, -12)
        return tuple(out)

    @staticmethod
    def _statement_freshness(card: HeldCard, covered: set[str], today: date) -> dict:
        """How far a statement-tracked card has fallen behind on uploads.

        The newest month a statement could vouch for is last month. With one month of
        grace for issuers whose statement closes late, a card is due once its newest
        covered month is older than that. Cards with no statements at all are never due:
        they are tracked by hand, and the coverage sensor already says so.
        """
        if not covered or not card.is_active(today):
            return {}
        last = max(covered)
        expected = add_months(today.replace(day=1), -1)
        expected_month = f"{expected.year:04d}-{expected.month:02d}"
        y, m = (int(x) for x in last.split("-"))
        behind = max((expected.year - y) * 12 + (expected.month - m), 0)
        return {
            "last_statement_month": last,
            "expected_statement_month": expected_month,
            "statement_months_behind": behind,
            "statement_due": behind > STATEMENT_GRACE_MONTHS,
        }

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
