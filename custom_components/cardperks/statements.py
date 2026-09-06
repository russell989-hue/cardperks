"""Parse issuer statement exports (Chase, American Express) into fee and credit events.

Pure Python. Matching is rule-based: fee lines by issuer convention, credit lines by the
`statement_match` regex list on each catalog benefit.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .models import Product

CHASE_FEE_RE = re.compile(r"ANNUAL MEMBERSHIP FEE", re.I)
AMEX_FEE_RE = re.compile(r"(RENEWAL )?MEMBERSHIP FEE", re.I)
CREDIT_HINT_RE = re.compile(r"\bCREDIT\b", re.I)


@dataclass(frozen=True, slots=True)
class StatementRow:
    date: date
    description: str
    amount: float  # positive = charge, negative = credit/refund (normalised)
    kind: str  # "fee" | "credit" | "other"
    card_last4: str | None = None


@dataclass(slots=True)
class ParsedStatement:
    issuer: str  # "chase" | "amex"
    rows: list[StatementRow]
    last4s: set[str] = field(default_factory=set)
    filename_last4: str | None = None

    @property
    def fee_rows(self) -> list[StatementRow]:
        return [r for r in self.rows if r.kind == "fee"]

    @property
    def credit_rows(self) -> list[StatementRow]:
        return [r for r in self.rows if r.kind == "credit"]

    @property
    def date_range(self) -> tuple[date, date] | None:
        if not self.rows:
            return None
        ds = [r.date for r in self.rows]
        return min(ds), max(ds)


@dataclass(frozen=True, slots=True)
class CreditMatch:
    row: StatementRow
    benefit_id: str


@dataclass(slots=True)
class MatchResult:
    matched: list[CreditMatch] = field(default_factory=list)
    unmatched: list[StatementRow] = field(default_factory=list)


def _parse_date(value: str) -> date:
    v = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def _amount(value: str) -> float:
    return float(value.replace("$", "").replace(",", "").strip() or 0)


def last4_from_filename(name: str | None) -> str | None:
    if not name:
        return None
    m = re.search(r"(\d{4})_Activity", name) or re.search(r"(?<!\d)(\d{4})(?!\d)", name)
    return m.group(1) if m else None


def detect_issuer(header: list[str]) -> str | None:
    cols = {h.strip().lower() for h in header}
    if {"transaction date", "post date", "description", "type", "amount"} <= cols:
        return "chase"
    if {"date", "description", "amount"} <= cols and (
        "appears on your statement as" in cols or "extended details" in cols
    ):
        return "amex"
    return None


def parse_statement(text: str, filename: str | None = None) -> ParsedStatement:
    """Parse a raw CSV export. Raises ValueError if the format is not recognised."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration as err:
        raise ValueError("empty file") from err
    issuer = detect_issuer(header)
    if issuer is None:
        raise ValueError("not a recognised Chase or American Express export")
    idx = {h.strip().lower(): i for i, h in enumerate(header)}
    rows: list[StatementRow] = []
    last4s: set[str] = set()

    def col(r: list[str], name: str) -> str:
        i = idx.get(name)
        return r[i].strip() if i is not None and i < len(r) else ""

    for r in reader:
        if not any(c.strip() for c in r):
            continue
        try:
            if issuer == "chase":
                d = _parse_date(col(r, "transaction date"))
                desc = col(r, "description")
                # Chase: negative = charge, positive = payment/credit. Normalise to charge-positive.
                amt = -_amount(col(r, "amount"))
                typ = col(r, "type").lower()
                last4 = col(r, "card") or None
                if last4:
                    last4s.add(last4)
                if typ == "fee" and CHASE_FEE_RE.search(desc):
                    kind = "fee"
                elif typ == "adjustment" and amt < 0:
                    kind = "credit"
                else:
                    kind = "other"
            else:
                d = _parse_date(col(r, "date"))
                desc = col(r, "description")
                amt = _amount(col(r, "amount"))  # Amex: positive = charge, negative = credit
                last4 = None
                if AMEX_FEE_RE.search(desc) and amt > 0:
                    kind = "fee"
                elif amt < 0 and CREDIT_HINT_RE.search(desc):
                    kind = "credit"
                else:
                    kind = "other"
        except ValueError:
            continue
        rows.append(StatementRow(d, desc, amt, kind, last4))

    return ParsedStatement(
        issuer=issuer, rows=rows, last4s=last4s, filename_last4=last4_from_filename(filename)
    )


def match_credits(parsed: ParsedStatement, product: Product) -> MatchResult:
    """Map credit rows onto catalog benefits using each benefit's statement_match patterns."""
    result = MatchResult()
    compiled = [
        (b.id, [re.compile(p, re.I) for p in b.statement_match])
        for b in product.benefits
        if b.statement_match
    ]
    for row in parsed.credit_rows:
        hit = next(
            (bid for bid, pats in compiled if any(p.search(row.description) for p in pats)), None
        )
        if hit:
            result.matched.append(CreditMatch(row, hit))
        else:
            result.unmatched.append(row)
    return result


def latest_fee(parsed: ParsedStatement) -> StatementRow | None:
    fees = parsed.fee_rows
    return max(fees, key=lambda r: r.date) if fees else None
