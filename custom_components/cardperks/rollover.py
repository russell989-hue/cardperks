"""Daily rollover: close expired benefit periods, open current ones. Pure function."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from .const import HISTORY_RETENTION_DAYS, BenefitStatus, Cadence
from .models import (
    Benefit,
    BenefitInstance,
    Catalog,
    HeldCard,
    HistoryRecord,
    StateDocument,
    instance_key,
)
from .periods import Period, compute_period, period_after


@dataclass(slots=True)
class RolloverResult:
    changed: bool = False
    opened: int = 0
    closed: int = 0
    gaps: int = 0


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _amount_for(benefit: Benefit, perk_values: Mapping[str, float]) -> float | None:
    if benefit.amount is not None and benefit.unit == "USD":
        return float(benefit.amount)
    if benefit.type.value in ("perk", "insurance"):
        return benefit.value(perk_values.get(benefit.id))
    return None  # points/miles earnings carry no dollar amount


def _close(
    doc: StateDocument,
    inst: BenefitInstance,
    now_iso: str,
    closed_by: str,
    final_status: str | None = None,
) -> None:
    doc.history.append(
        HistoryRecord(
            held_card_id=inst.held_card_id,
            benefit_id=inst.benefit_id,
            period_start=inst.period_start,
            period_end=inst.period_end,
            final_status=final_status or str(inst.status),
            amount=inst.amount,
            amount_used=inst.amount_used,
            closed_at=now_iso,
            closed_by=closed_by,
        )
    )
    doc.instances.pop(inst.key, None)


def _open(
    doc: StateDocument,
    card: HeldCard,
    benefit: Benefit,
    period: Period,
    now_iso: str,
    sticky_na: bool = False,
    perk_values: Mapping[str, float] | None = None,
) -> BenefitInstance:
    na = sticky_na or benefit.id in card.not_applicable
    inst = BenefitInstance(
        held_card_id=card.id,
        benefit_id=benefit.id,
        period_start=period.start.isoformat(),
        period_end=_iso(period.end),
        status=BenefitStatus.NA if na else BenefitStatus.UNUSED,
        amount=_amount_for(benefit, perk_values or {}),
        sticky_na=na,
        updated_at=now_iso,
    )
    doc.instances[inst.key] = inst
    return inst


def _card_period(card: HeldCard, benefit: Benefit, today: date) -> Period | None:
    return compute_period(
        today,
        benefit.cadence,
        benefit.reset,
        card.open_date,
        card.fee_month,
        benefit.expires_days_after_open,
    )


def rollover(
    doc: StateDocument,
    cards: Iterable[HeldCard],
    catalog: Catalog,
    today: date,
    now_iso: str,
    perk_values: Mapping[str, Mapping[str, float]] | None = None,
) -> RolloverResult:
    """Bring every benefit instance up to date with `today`. Idempotent.

    `perk_values` are the dollars each perk is worth per card; the coordinator passes
    the effective values with shared perks already split. Defaults to the raw ones.
    """
    result = RolloverResult()
    pv = perk_values if perk_values is not None else doc.perk_values
    active_cards = {c.id: c for c in cards}

    # 1. Close instances belonging to closed/removed cards or benefits no longer applicable.
    for key in list(doc.instances):
        inst = doc.instances[key]
        card = active_cards.get(inst.held_card_id)
        product = catalog.get(card.product_id) if card else None
        benefit = product.benefit(inst.benefit_id) if product else None
        if card is None or product is None:
            continue  # orphan: keep untouched (card may come back after a reload)
        if benefit is None:
            # The catalog dropped or renamed this benefit: close it out rather than leave
            # an instance nothing can see, which would still count toward unused value.
            _close(doc, inst, now_iso, "removed")
            result.closed += 1
            result.changed = True
            continue
        if not card.is_active(today):
            _close(
                doc, inst, now_iso, str(card.status) if card.status != "active" else "closed_card"
            )
            result.closed += 1
            result.changed = True
        elif not benefit.applies_to_role(card.role) or (
            benefit.conditional and benefit.id not in card.enabled_conditional
        ):
            # Catalog corrected: this benefit no longer applies to this cardholder role.
            _close(doc, inst, now_iso, "not_applicable")
            result.closed += 1
            result.changed = True
        elif benefit.id in card.not_applicable and not inst.sticky_na:
            # Marked not applicable on the card: take effect in the open period, not the next.
            inst.status = BenefitStatus.NA
            inst.sticky_na = True
            inst.updated_at = now_iso
            result.changed = True
        elif benefit.id not in card.not_applicable and inst.sticky_na:
            inst.sticky_na = False
            if inst.status is BenefitStatus.NA:
                inst.status = BenefitStatus.PARTIAL if inst.amount_used else BenefitStatus.UNUSED
            inst.updated_at = now_iso
            result.changed = True

    # 2. For every active card/benefit, open or roll the current period.
    for card in active_cards.values():
        if not card.is_active(today):
            continue
        product = catalog.get(card.product_id)
        if product is None:
            continue
        for benefit in product.benefits_for(card):
            key = instance_key(card.id, benefit.id)
            expected = _card_period(card, benefit, today)
            if expected is None:
                continue
            inst = doc.instances.get(key)

            if inst is None:
                if benefit.cadence is Cadence.ONE_TIME and any(
                    h.held_card_id == card.id and h.benefit_id == benefit.id for h in doc.history
                ):
                    continue  # one-time benefit already closed; never reopen
                if expected.end is not None and expected.end < today:
                    continue  # e.g. one-time already expired before tracking began
                _open(doc, card, benefit, expected, now_iso, perk_values=pv.get(card.id, {}))
                result.opened += 1
                result.changed = True
                continue

            inst_end = date.fromisoformat(inst.period_end) if inst.period_end else None
            inst_start = date.fromisoformat(inst.period_start)

            if inst_end is not None and inst_end < today:
                sticky = inst.sticky_na
                _close(doc, inst, now_iso, "rollover")
                result.closed += 1
                result.changed = True
                if benefit.cadence is Cadence.ONE_TIME:
                    continue
                # Backfill periods that were missed entirely (HA was off).
                p = period_after(
                    inst_end, benefit.cadence, benefit.reset, card.open_date, card.fee_month
                )
                while p is not None and p.end is not None and p.end < expected.start:
                    doc.history.append(
                        HistoryRecord(
                            held_card_id=card.id,
                            benefit_id=benefit.id,
                            period_start=p.start.isoformat(),
                            period_end=p.end.isoformat(),
                            final_status="unknown",
                            amount=_amount_for(benefit, pv.get(card.id, {})),
                            amount_used=0.0,
                            closed_at=now_iso,
                            closed_by="gap",
                        )
                    )
                    result.gaps += 1
                    p = period_after(
                        p.end, benefit.cadence, benefit.reset, card.open_date, card.fee_month
                    )
                _open(
                    doc,
                    card,
                    benefit,
                    expected,
                    now_iso,
                    sticky_na=sticky,
                    perk_values=pv.get(card.id, {}),
                )
                result.opened += 1
            elif inst_start != expected.start and benefit.cadence is not Cadence.ONE_TIME:
                # Anchor changed (reconfigured open date / fee month).
                sticky = inst.sticky_na
                _close(doc, inst, now_iso, "reanchor")
                _open(
                    doc,
                    card,
                    benefit,
                    expected,
                    now_iso,
                    sticky_na=sticky,
                    perk_values=pv.get(card.id, {}),
                )
                result.closed += 1
                result.opened += 1
                result.changed = True

    # 3. Trim history.
    cutoff = (today - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    before = len(doc.history)
    doc.history = [h for h in doc.history if (h.period_end or h.period_start) >= cutoff]
    if len(doc.history) != before:
        result.changed = True

    if doc.last_rollover != today.isoformat():
        doc.last_rollover = today.isoformat()
        result.changed = True
    return result
