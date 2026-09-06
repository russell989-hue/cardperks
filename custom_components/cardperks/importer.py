"""Bulk import of owners and cards from pasted CSV rows."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .const import (
    CONF_ANNUAL_FEE,
    CONF_CLOSE_DATE,
    CONF_ENABLED_CONDITIONAL,
    CONF_FEE_MONTH,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_NOTES,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PREVIOUS_LAST4,
    CONF_PRODUCT_ID,
    CONF_ROLE,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
    Role,
)
from .models import Catalog, Product

# Accepted column names (lower-cased) -> canonical key.
COLUMN_ALIASES: dict[str, str] = {
    "owner": "owner",
    "issuer": "issuer",
    "product": "product",
    "card_product": "product",
    "card": "product",
    "role": "role",
    "parent_last4": "parent_last4",
    "parent_owner": "parent_owner",
    "primary_holder_if_au": "parent_owner",
    "open_date": "open_date",
    "opened": "open_date",
    "fee_month": "fee_month",
    "fee_anniversary_month": "fee_month",
    "last4": "last4",
    "last_4": "last4",
    "nickname": "nickname",
    "notes": "notes",
    "annual_fee": "annual_fee",
    "fee": "annual_fee",
    "previous_last4": "previous_last4",
    "old_last4": "previous_last4",
}

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}

ROLE_ALIASES = {
    "primary": Role.PRIMARY,
    "p": Role.PRIMARY,
    "": Role.PRIMARY,
    "authorized_user": Role.AUTHORIZED_USER,
    "authorized user": Role.AUTHORIZED_USER,
    "au": Role.AUTHORIZED_USER,
}


@dataclass(slots=True)
class ImportResult:
    created_owners: list[str] = field(default_factory=list)
    created_cards: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_owners": self.created_owners,
            "created_cards": self.created_cards,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def parse_month(value: str) -> int | None:
    v = value.strip().lower()
    if not v:
        return None
    if v.isdigit() and 1 <= int(v) <= 12:
        return int(v)
    return MONTHS.get(v[:3])


def parse_date(value: str) -> date | None:
    v = value.strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y-%m"):
        try:
            from datetime import datetime

            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def _norm(s: str) -> str:
    return slugify(s.strip().lower())


def find_product(catalog: Catalog, issuer: str, product: str) -> Product | None:
    """Match by product id, or by issuer + product name (case/punctuation-insensitive)."""
    p = catalog.get(product.strip())
    if p is not None:
        return p
    want_issuer = _norm(issuer)
    want_name = _norm(product)
    candidates = [
        p
        for p in catalog.products.values()
        if (not want_issuer or want_issuer in (_norm(p.issuer), _norm(p.issuer_name)))
    ]
    for p in candidates:
        if _norm(p.name) == want_name:
            return p
    # loose: all words of the requested name appear in the product name (e.g. "Platinum")
    words = set(want_name.split("_"))
    loose = [p for p in candidates if words <= set(_norm(p.name).split("_"))]
    return loose[0] if len(loose) == 1 else None


def parse_rows(text: str) -> list[dict[str, str]]:
    """Parse CSV text into canonical-key rows. Header row required."""
    reader = csv.reader(io.StringIO(text.strip()))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [COLUMN_ALIASES.get(h.strip().lower(), h.strip().lower()) for h in rows[0]]
    if "owner" not in header or "product" not in header:
        raise ValueError("header must include at least 'owner' and 'product' columns")
    out = []
    for r in rows[1:]:
        row = {header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))}
        out.append(row)
    return out


async def async_import_cards(
    hass: HomeAssistant, entry: ConfigEntry, catalog: Catalog, text: str
) -> ImportResult:
    result = ImportResult()
    try:
        rows = parse_rows(text)
    except ValueError as err:
        result.errors.append(str(err))
        return result

    owners: dict[str, ConfigSubentry] = {
        s.unique_id or slugify(s.title): s
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_OWNER
    }
    cards: list[ConfigSubentry] = [
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CARD
    ]

    def _owner(name: str) -> ConfigSubentry:
        slug = slugify(name)
        if slug in owners:
            return owners[slug]
        sub = ConfigSubentry(
            data=MappingProxyType({CONF_NAME: name}),
            subentry_type=SUBENTRY_OWNER,
            title=name,
            unique_id=slug,
        )
        hass.config_entries.async_add_subentry(entry, sub)
        owners[slug] = sub
        result.created_owners.append(name)
        return sub

    # Primaries first so authorized-user rows can find their parent.
    ordered = sorted(
        enumerate(rows),
        key=lambda ir: (
            ROLE_ALIASES.get(ir[1].get("role", "").lower(), Role.PRIMARY) is Role.AUTHORIZED_USER
        ),
    )
    for idx, row in ordered:
        label = f"row {idx + 2}"
        try:
            owner_name = row.get("owner", "")
            if not owner_name:
                raise ValueError("owner is empty")
            product = find_product(catalog, row.get("issuer", ""), row.get("product", ""))
            if product is None:
                raise ValueError(
                    f"unknown product {row.get('issuer', '')!r} / {row.get('product', '')!r}"
                )
            role = ROLE_ALIASES.get(row.get("role", "").lower())
            if role is None:
                raise ValueError(f"unknown role {row.get('role')!r}")
            last4 = row.get("last4", "")
            if last4 and not (last4.isdigit() and len(last4) == 4):
                raise ValueError(f"last4 must be four digits, got {last4!r}")
            open_date = parse_date(row.get("open_date", ""))
            fee_month = parse_month(row.get("fee_month", ""))
            fee_raw = row.get("annual_fee", "").strip().lstrip("$")
            annual_fee: float | None = None
            if fee_raw:
                try:
                    annual_fee = float(fee_raw)
                except ValueError as err:
                    raise ValueError(f"annual_fee must be a number, got {fee_raw!r}") from err
            if row.get("fee_month") and fee_month is None:
                raise ValueError(f"unknown fee month {row.get('fee_month')!r}")

            owner = _owner(owner_name)

            dup = next(
                (
                    c
                    for c in cards
                    if c.data.get(CONF_OWNER_ID) == owner.subentry_id
                    and c.data.get(CONF_PRODUCT_ID) == product.id
                    and (c.data.get(CONF_LAST4) or "") == last4
                    and Role(c.data.get(CONF_ROLE, "primary")) is role
                ),
                None,
            )
            if dup is not None:
                result.skipped.append(f"{label}: already have {dup.title}")
                continue

            parent_id = None
            if role is Role.AUTHORIZED_USER:
                primaries = [
                    c
                    for c in cards
                    if c.data.get(CONF_PRODUCT_ID) == product.id
                    and Role(c.data.get(CONF_ROLE, "primary")) is Role.PRIMARY
                ]
                if row.get("parent_last4"):
                    primaries = [
                        c for c in primaries if c.data.get(CONF_LAST4) == row["parent_last4"]
                    ]
                elif row.get("parent_owner"):
                    want = slugify(row["parent_owner"])
                    primaries = [
                        c
                        for c in primaries
                        if owners.get(want) is not None
                        and c.data.get(CONF_OWNER_ID) == owners[want].subentry_id
                    ]
                if len(primaries) != 1:
                    raise ValueError(
                        "authorized user needs exactly one matching primary card "
                        "(add parent_last4 or parent_owner)"
                    )
                parent = primaries[0]
                parent_id = parent.subentry_id
                open_date = open_date or (
                    date.fromisoformat(parent.data[CONF_OPEN_DATE])
                    if parent.data.get(CONF_OPEN_DATE)
                    else None
                )
                fee_month = fee_month or parent.data.get(CONF_FEE_MONTH)
            elif open_date is None and fee_month is None:
                raise ValueError("primary card needs open_date or fee_month")

            nickname = row.get("nickname", "") or None
            au = " (AU)" if role is Role.AUTHORIZED_USER else ""
            suffix = f" ·{last4}" if last4 else ""
            title = nickname or f"{product.name}{au} ({owner.title}{suffix})"
            data = {
                CONF_OWNER_ID: owner.subentry_id,
                CONF_PRODUCT_ID: product.id,
                CONF_ROLE: str(role),
                CONF_PARENT_CARD_ID: parent_id,
                CONF_OPEN_DATE: open_date.isoformat() if open_date else None,
                CONF_FEE_MONTH: fee_month,
                CONF_LAST4: last4 or None,
                CONF_NICKNAME: nickname,
                CONF_NOTES: row.get("notes", "") or None,
                CONF_ANNUAL_FEE: annual_fee,
                CONF_ENABLED_CONDITIONAL: [],
                CONF_PREVIOUS_LAST4: [
                    p for p in re.split(r"[,\s]+", row.get("previous_last4", "").strip()) if p
                ],
                CONF_CLOSE_DATE: None,
            }
            sub = ConfigSubentry(
                data=MappingProxyType(data),
                subentry_type=SUBENTRY_CARD,
                title=title,
                unique_id=None,
            )
            hass.config_entries.async_add_subentry(entry, sub)
            cards.append(sub)
            result.created_cards.append(title)
        except ValueError as err:
            result.errors.append(f"{label}: {err}")
    return result
