"""Apply a parsed statement to held cards. Shared by the upload flow and the service.

The flow and the `import_statement` service both end here, so a file dropped in a
folder and a file uploaded in the UI produce the same records, the same receipt and
the same summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ANNUAL_FEE,
    CONF_FEE_MONTH,
    CONF_LAST4,
    CONF_OPEN_DATE,
    CONF_PREVIOUS_LAST4,
    CONF_PRODUCT_ID,
    DATA_IMPORTING,
    DOMAIN,
    SUBENTRY_CARD,
)
from .models import Catalog
from .statements import ParsedStatement, StatementRow, latest_fee, match_credits


@dataclass(slots=True)
class StatementApplied:
    """What one pass over one card did."""

    card_id: str
    card_title: str
    rows: int
    applied: dict[str, float] = field(default_factory=dict)  # benefit id -> dollars recorded
    benefit_names: dict[str, str] = field(default_factory=dict)
    duplicates: int = 0
    unmatched: list[StatementRow] = field(default_factory=list)
    fee_note: str = "not applied"
    fee_changed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card": self.card_title,
            "rows": self.rows,
            "applied": {self.benefit_names.get(b, b): amt for b, amt in self.applied.items()},
            "applied_total": round(sum(self.applied.values()), 2),
            "duplicates": self.duplicates,
            "unmatched": [
                {"date": r.date.isoformat(), "description": r.description, "amount": abs(r.amount)}
                for r in self.unmatched
            ],
            "fee": self.fee_note,
        }


def card_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    return [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CARD]


def cards_for_issuer(entry: ConfigEntry, catalog: Catalog, issuer: str) -> list[ConfigSubentry]:
    out = []
    for s in card_subentries(entry):
        product = catalog.get(s.data.get(CONF_PRODUCT_ID, ""))
        if product is not None and product.issuer == issuer:
            out.append(s)
    return out


def subentry_last4s(sub: ConfigSubentry) -> set[str]:
    """Every number this account has had, current and former."""
    out = set(sub.data.get(CONF_PREVIOUS_LAST4) or [])
    if sub.data.get(CONF_LAST4):
        out.add(sub.data[CONF_LAST4])
    return out


def cards_in_statement(entry: ConfigEntry, parsed: ParsedStatement) -> list[ConfigSubentry]:
    """Configured cards whose numbers appear in the file, in subentry order.

    Only exports that carry a per-row card number (Chase, Capital One) can say which
    cards they cover; an Amex file names none and matches nothing here.
    """
    if not parsed.last4s:
        return []
    return [s for s in card_subentries(entry) if subentry_last4s(s) & parsed.last4s]


def apply_statement(
    hass: HomeAssistant,
    entry: ConfigEntry,
    card_id: str,
    parsed: ParsedStatement,
    *,
    file_hash: str,
    filename: str | None,
    apply_fee: bool,
) -> StatementApplied:
    """Record one card's credits and coverage from the file. Commits the state document.

    Only this account's rows are used: one Chase export often covers several cards, and
    a replaced card appears under both its old and new numbers. Idempotent: a credit
    line already imported is counted as a duplicate and changes nothing.
    """
    coordinator = entry.runtime_data
    card = coordinator.card(card_id)
    product = coordinator.catalog.get(card.product_id)

    mine = parsed.for_last4(card.all_last4)
    result = match_credits(mine, product) if product is not None else None
    out = StatementApplied(
        card_id=card_id,
        card_title=card.title,
        rows=len(mine.rows),
        benefit_names={b.id: b.name for b in product.benefits} if product else {},
    )

    if result is not None:
        for m in result.matched:
            ok = coordinator.record_statement_usage(
                card_id, m.benefit_id, m.row.date, abs(m.row.amount), m.row.description[:60]
            )
            if ok:
                out.applied[m.benefit_id] = round(
                    out.applied.get(m.benefit_id, 0.0) + abs(m.row.amount), 2
                )
            else:
                out.duplicates += 1
        out.unmatched = list(result.unmatched)

    rng = mine.date_range
    coordinator.record_import(
        card_id,
        file_hash=file_hash,
        filename=filename,
        issuer=mine.issuer,
        months=mine.months(),
        first_date=rng[0].isoformat() if rng else None,
        last_date=rng[1].isoformat() if rng else None,
        rows=len(mine.rows),
        credit_rows=len(mine.credit_rows),
        matched=len(result.matched) if result else 0,
        applied=sum(out.applied.values()),
    )
    coordinator.commit()

    # Every fee line, by date: the per-year history reads these back.
    if mine.fee_rows:
        seen_fees = coordinator.doc.fees_seen.setdefault(card_id, {})
        for row in mine.fee_rows:
            seen_fees[row.date.isoformat()] = round(abs(row.amount), 2)
    fee = latest_fee(mine)
    seen = coordinator.doc.fee_seen.get(card_id)
    if fee is not None and seen is not None and fee.date.isoformat() < seen:
        # This file's fee line is older than one already applied (a prior year's export
        # imported after this year's): it says nothing about the fee now.
        out.fee_note = (
            f"{fee.amount:.0f} on {fee.date.isoformat()} (older than the fee already recorded)"
        )
        fee = None
    if apply_fee and fee is not None:
        coordinator.doc.fee_seen[card_id] = fee.date.isoformat()
        sub = entry.subentries[card_id]
        new_data = dict(sub.data)
        changed = False
        if not new_data.get(CONF_FEE_MONTH) and not new_data.get(CONF_OPEN_DATE):
            new_data[CONF_FEE_MONTH] = fee.date.month
            changed = True
        catalog_fee = product.annual_fee if product else None
        if (
            fee.amount > 0
            and fee.amount != catalog_fee
            and new_data.get(CONF_ANNUAL_FEE) != fee.amount
        ):
            new_data[CONF_ANNUAL_FEE] = fee.amount
            changed = True
        if changed:
            hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
            try:
                hass.config_entries.async_update_subentry(entry, sub, data=new_data)
            finally:
                hass.data[DOMAIN][DATA_IMPORTING] = False
            hass.config_entries.async_schedule_reload(entry.entry_id)
            out.fee_changed = True
            out.fee_note = (
                f"fee month set to {fee.date.strftime('%B')}, annual fee {fee.amount:.0f}"
            )
        else:
            out.fee_note = f"{fee.amount:.0f} on {fee.date.isoformat()} (already configured)"
    elif fee is None and out.fee_note == "not applied":
        out.fee_note = "no fee line for this card in the export"
    return out


def summarise(results: list[StatementApplied], others: set[str]) -> dict[str, str]:
    """Placeholders for the flow's closing message, for one card or several."""

    def _fmt(lines: list[str]) -> str:
        return "\n".join(f"- {line}" for line in lines) if lines else "- none"

    many = len(results) > 1
    applied: list[str] = []
    unmatched: list[str] = []
    fees: list[str] = []
    for r in results:
        prefix = f"{r.card_title}: " if many else ""
        applied.extend(
            f"{prefix}{r.benefit_names.get(b, b)}: {amt:.2f}" for b, amt in r.applied.items()
        )
        unmatched.extend(
            f"{prefix}{row.date.isoformat()} {row.description} {abs(row.amount):.2f}"
            for row in r.unmatched
        )
        fees.append(f"{prefix}{r.fee_note}")
    note = ""
    if others:
        note = (
            f"This file also covers card(s) {', '.join(sorted(others))} that are not set up; "
            "their rows were left alone. Import it again and add that card.\n\n"
        )
    return {
        "card": ", ".join(r.card_title for r in results),
        "note": note,
        "fee": "\n".join(f"- {f}" for f in fees) if many else fees[0] if fees else "not applied",
        "applied": _fmt(applied),
        "duplicates": str(sum(r.duplicates for r in results)),
        "unmatched": _fmt(unmatched[:15]),
    }
