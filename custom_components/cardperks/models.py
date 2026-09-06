"""Data models for CardPerks. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .const import (
    PERIODS_PER_YEAR,
    AppliesTo,
    BenefitStatus,
    BenefitType,
    Cadence,
    CardStatus,
    ResetRule,
    Role,
)

# --------------------------------------------------------------------------- catalog

CADENCE_TAGS: dict[Cadence, str] = {
    Cadence.MONTHLY: "monthly",
    Cadence.QUARTERLY: "quarterly",
    Cadence.SEMIANNUAL: "every 6 months",
    Cadence.ONE_TIME: "one-time",
    Cadence.PER_ANNIVERSARY: "each anniversary",
}


@dataclass(frozen=True, slots=True)
class Benefit:
    id: str
    name: str
    type: BenefitType
    cadence: Cadence
    amount: float | None
    unit: str
    reset: ResetRule
    enrollment_required: bool
    applies_to: AppliesTo
    default_value: float | None = None
    expires_days_after_open: int | None = None
    spend_required: float | None = None
    notes: str | None = None
    statement_match: tuple[str, ...] = ()  # regexes matched against statement descriptions
    conditional: bool = False  # only some cardholders qualify; off unless enabled per card
    condition: str | None = None  # human-readable qualification, shown in the card form

    def applies_to_role(self, role: Role) -> bool:
        if role is Role.PRIMARY:
            return True
        return self.applies_to in (AppliesTo.PRIMARY_AND_AU, AppliesTo.AU_OWN_ALLOTMENT)

    @property
    def label(self) -> str:
        """The name, with how often it comes round when that is not yearly.

        "Uber One membership credit (monthly)" tells you at a glance how long you have
        to use it; yearly benefits carry no tag, since that is the default expectation.
        This is the name entities and dashboards show.
        """
        tag = CADENCE_TAGS.get(self.cadence)
        return f"{self.name} ({tag})" if tag else self.name

    @property
    def is_one_time(self) -> bool:
        return self.cadence is Cadence.ONE_TIME

    @property
    def is_dollar(self) -> bool:
        """Whether this benefit is measured in dollars rather than points or miles."""
        if self.type in (BenefitType.PERK, BenefitType.INSURANCE, BenefitType.REBATE):
            return True
        return self.amount is not None and self.unit == "USD"

    @property
    def is_uncapped(self) -> bool:
        """A rebate returns a share of whatever you spend.

        There is no pool to draw down, nothing to check off and nothing to forfeit.
        Statements are its only source of truth, and a year of it is worth whatever it
        returned.
        """
        return self.type is BenefitType.REBATE

    @property
    def periods_per_year(self) -> int:
        return PERIODS_PER_YEAR.get(self.cadence, 0)

    def annual_value(self, perk_override: float | None = None) -> float:
        """What this benefit is worth over a year if fully used."""
        if not self.is_dollar:
            return 0.0
        return round(self.value(perk_override) * (self.periods_per_year or 1), 2)

    def value(self, perk_override: float | None = None) -> float:
        """Dollar value of one period of this benefit."""
        if self.amount is not None and self.unit == "USD":
            return float(self.amount)
        if perk_override is not None:
            return float(perk_override)
        return float(self.default_value or 0.0)


@dataclass(frozen=True, slots=True)
class EarningRate:
    category: str
    multiplier: float
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class AuTerms:
    fee: float = 0.0
    own_lounge_access: bool = False
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class Product:
    id: str
    issuer: str
    issuer_name: str
    name: str
    annual_fee: float
    currency: str
    default_point_value: float
    reports_to_personal_credit: bool
    last_verified: date
    source_url: str
    benefits: tuple[Benefit, ...]
    earning_rates: tuple[EarningRate, ...]
    au_terms: AuTerms
    needs_verification: bool = False
    origin: str = "shipped"

    def benefit(self, benefit_id: str) -> Benefit | None:
        for b in self.benefits:
            if b.id == benefit_id:
                return b
        return None

    def benefits_for_role(self, role: Role) -> tuple[Benefit, ...]:
        return tuple(b for b in self.benefits if b.applies_to_role(role))

    def conditional_benefits(self, role: Role) -> tuple[Benefit, ...]:
        return tuple(b for b in self.benefits_for_role(role) if b.conditional)

    def benefits_for(self, card: HeldCard) -> tuple[Benefit, ...]:
        """Benefits active for this specific card: role-eligible, conditionals opted in."""
        enabled = set(card.enabled_conditional)
        return tuple(
            b for b in self.benefits_for_role(card.role) if not b.conditional or b.id in enabled
        )


@dataclass(frozen=True, slots=True)
class CatalogProblem:
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class Catalog:
    products: Mapping[str, Product]

    def by_issuer(self) -> dict[str, list[Product]]:
        out: dict[str, list[Product]] = {}
        for p in self.products.values():
            out.setdefault(p.issuer, []).append(p)
        for lst in out.values():
            lst.sort(key=lambda p: p.name)
        return out

    def issuers(self) -> dict[str, str]:
        """issuer slug -> display name."""
        return {p.issuer: p.issuer_name for p in self.products.values()}

    def get(self, product_id: str) -> Product | None:
        return self.products.get(product_id)


# --------------------------------------------------------------------------- config


@dataclass(frozen=True, slots=True)
class Owner:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class HeldCard:
    id: str
    owner_id: str
    product_id: str
    role: Role
    title: str
    parent_card_id: str | None = None
    open_date: date | None = None
    fee_month: int | None = None
    last4: str | None = None
    nickname: str | None = None
    close_date: date | None = None
    notes: str | None = None
    annual_fee: float | None = None  # overrides the catalog fee (grandfathered pricing)
    enabled_conditional: tuple[str, ...] = ()  # conditional benefit ids this card qualifies for
    previous_last4: tuple[str, ...] = ()  # numbers this account had before replacement
    not_applicable: tuple[str, ...] = ()  # benefit ids that do not apply to this holder
    color: str | None = None  # seed only; the live value lives in the state document
    status: CardStatus = CardStatus.ACTIVE  # merged in from the state document

    @property
    def all_last4(self) -> frozenset[str]:
        """Every card number this account has had.

        A replaced card (lost, stolen, expired) keeps the same account and benefit
        periods but gets a new number, and old statements still carry the old one.
        """
        return frozenset(x for x in (self.last4, *self.previous_last4) if x)

    def is_active(self, today: date) -> bool:
        if self.status is not CardStatus.ACTIVE:
            return False
        return self.close_date is None or self.close_date >= today


# --------------------------------------------------------------------------- state


@dataclass(slots=True)
class UsageEvent:
    date: str
    amount: float
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date, "amount": self.amount, "note": self.note}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> UsageEvent:
        return cls(date=d["date"], amount=float(d["amount"]), note=d.get("note"))


@dataclass(slots=True)
class BenefitInstance:
    held_card_id: str
    benefit_id: str
    period_start: str
    period_end: str | None
    status: BenefitStatus = BenefitStatus.UNUSED
    amount: float | None = None
    amount_used: float = 0.0
    uses: list[UsageEvent] = field(default_factory=list)
    sticky_na: bool = False
    updated_at: str | None = None

    @property
    def key(self) -> str:
        return instance_key(self.held_card_id, self.benefit_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "held_card_id": self.held_card_id,
            "benefit_id": self.benefit_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "status": str(self.status),
            "amount": self.amount,
            "amount_used": self.amount_used,
            "uses": [u.to_dict() for u in self.uses],
            "sticky_na": self.sticky_na,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> BenefitInstance:
        return cls(
            held_card_id=d["held_card_id"],
            benefit_id=d["benefit_id"],
            period_start=d["period_start"],
            period_end=d.get("period_end"),
            status=BenefitStatus(d.get("status", "unused")),
            amount=d.get("amount"),
            amount_used=float(d.get("amount_used", 0.0)),
            uses=[UsageEvent.from_dict(u) for u in d.get("uses", [])],
            sticky_na=bool(d.get("sticky_na", False)),
            updated_at=d.get("updated_at"),
        )


@dataclass(slots=True)
class HistoryRecord:
    held_card_id: str
    benefit_id: str
    period_start: str
    period_end: str | None
    final_status: str  # BenefitStatus value or "unknown"
    amount: float | None
    amount_used: float
    closed_at: str
    closed_by: str  # rollover | manual | gap | reanchor | closed_card

    def to_dict(self) -> dict[str, Any]:
        return {
            "held_card_id": self.held_card_id,
            "benefit_id": self.benefit_id,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "final_status": self.final_status,
            "amount": self.amount,
            "amount_used": self.amount_used,
            "closed_at": self.closed_at,
            "closed_by": self.closed_by,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> HistoryRecord:
        return cls(
            held_card_id=d["held_card_id"],
            benefit_id=d["benefit_id"],
            period_start=d["period_start"],
            period_end=d.get("period_end"),
            final_status=d.get("final_status", "unknown"),
            amount=d.get("amount"),
            amount_used=float(d.get("amount_used", 0.0)),
            closed_at=d["closed_at"],
            closed_by=d.get("closed_by", "rollover"),
        )


@dataclass(slots=True)
class SubTracker:
    required: float
    spent: float = 0.0
    deadline: str | None = None
    entries: list[UsageEvent] = field(default_factory=list)
    completed_on: str | None = None

    @property
    def completed(self) -> bool:
        return self.completed_on is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "spent": self.spent,
            "deadline": self.deadline,
            "entries": [e.to_dict() for e in self.entries],
            "completed_on": self.completed_on,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SubTracker:
        return cls(
            required=float(d["required"]),
            spent=float(d.get("spent", 0.0)),
            deadline=d.get("deadline"),
            entries=[UsageEvent.from_dict(e) for e in d.get("entries", [])],
            completed_on=d.get("completed_on"),
        )


@dataclass(slots=True)
class ImportRecord:
    """One statement upload. Kept so coverage can be explained and re-run."""

    id: str
    file_hash: str
    filename: str | None
    issuer: str
    held_card_id: str
    imported_at: str
    first_date: str | None
    last_date: str | None
    rows: int
    credit_rows: int
    matched: int
    applied: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file_hash": self.file_hash,
            "filename": self.filename,
            "issuer": self.issuer,
            "held_card_id": self.held_card_id,
            "imported_at": self.imported_at,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "rows": self.rows,
            "credit_rows": self.credit_rows,
            "matched": self.matched,
            "applied": self.applied,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ImportRecord:
        return cls(
            id=d["id"],
            file_hash=d.get("file_hash", ""),
            filename=d.get("filename"),
            issuer=d.get("issuer", ""),
            held_card_id=d["held_card_id"],
            imported_at=d.get("imported_at", ""),
            first_date=d.get("first_date"),
            last_date=d.get("last_date"),
            rows=int(d.get("rows", 0)),
            credit_rows=int(d.get("credit_rows", 0)),
            matched=int(d.get("matched", 0)),
            applied=float(d.get("applied", 0.0)),
        )


@dataclass(slots=True)
class StateDocument:
    """Mutable, persisted state. Serialised to the HA Store."""

    instances: dict[str, BenefitInstance] = field(default_factory=dict)
    history: list[HistoryRecord] = field(default_factory=list)
    sub_trackers: dict[str, SubTracker] = field(default_factory=dict)
    rotating_activations: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    perk_values: dict[str, dict[str, float]] = field(default_factory=dict)
    card_colors: dict[str, str] = field(default_factory=dict)
    card_status: dict[str, str] = field(default_factory=dict)  # card id -> CardStatus
    # card id -> {"YYYY-MM": import id}: months a statement actually vouches for.
    coverage: dict[str, dict[str, str]] = field(default_factory=dict)
    imports: list[ImportRecord] = field(default_factory=list)
    last_rollover: str | None = None
    imported_refs: set[str] = field(default_factory=set)  # dedupe keys for statement imports

    def to_dict(self) -> dict[str, Any]:
        return {
            "benefit_instances": {k: v.to_dict() for k, v in self.instances.items()},
            "history": [h.to_dict() for h in self.history],
            "sub_trackers": {k: v.to_dict() for k, v in self.sub_trackers.items()},
            "rotating_activations": self.rotating_activations,
            "perk_values": self.perk_values,
            "card_colors": self.card_colors,
            "card_status": self.card_status,
            "coverage": self.coverage,
            "imports": [i.to_dict() for i in self.imports],
            "last_rollover": self.last_rollover,
            "imported_refs": sorted(self.imported_refs),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> StateDocument:
        if not d:
            return cls()
        return cls(
            instances={
                k: BenefitInstance.from_dict(v) for k, v in d.get("benefit_instances", {}).items()
            },
            history=[HistoryRecord.from_dict(h) for h in d.get("history", [])],
            sub_trackers={k: SubTracker.from_dict(v) for k, v in d.get("sub_trackers", {}).items()},
            rotating_activations={
                k: {q: dict(a) for q, a in v.items()}
                for k, v in d.get("rotating_activations", {}).items()
            },
            perk_values={
                k: {bk: float(bv) for bk, bv in v.items()}
                for k, v in d.get("perk_values", {}).items()
            },
            card_colors=dict(d.get("card_colors", {})),
            card_status=dict(d.get("card_status", {})),
            coverage={k: dict(v) for k, v in d.get("coverage", {}).items()},
            imports=[ImportRecord.from_dict(i) for i in d.get("imports", [])],
            last_rollover=d.get("last_rollover"),
            imported_refs=set(d.get("imported_refs", [])),
        )


def instance_key(held_card_id: str, benefit_id: str) -> str:
    return f"{held_card_id}:{benefit_id}"


# --------------------------------------------------------------------------- snapshot


@dataclass(frozen=True, slots=True)
class ExpiringItem:
    held_card_id: str
    card_title: str
    benefit_id: str
    benefit_name: str
    period_end: date
    remaining: float


@dataclass(frozen=True, slots=True)
class Totals:
    """Dollars over the trailing twelve months.

    A period that closed unused is money gone, not money pending, so forfeited is
    tracked separately from what is still capturable. Periods with no usage evidence
    are counted as unknown rather than assumed lost: gaps backfilled by the rollover,
    and statement-credit periods no imported statement vouches for.
    """

    annual_value: float = 0.0
    captured: float = 0.0
    forfeited: float = 0.0
    unknown: float = 0.0
    open_remaining: float = 0.0

    @property
    def capture_rate(self) -> float | None:
        """Share of the annual value actually captured, 0-100."""
        if self.annual_value <= 0:
            return None
        return round(self.captured / self.annual_value * 100, 1)

    def plus(self, other: Totals) -> Totals:
        return Totals(
            annual_value=round(self.annual_value + other.annual_value, 2),
            captured=round(self.captured + other.captured, 2),
            forfeited=round(self.forfeited + other.forfeited, 2),
            unknown=round(self.unknown + other.unknown, 2),
            open_remaining=round(self.open_remaining + other.open_remaining, 2),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "annual_value": self.annual_value,
            "captured_12m": self.captured,
            "forfeited_12m": self.forfeited,
            "unknown_12m": self.unknown,
            "open_remaining": self.open_remaining,
            "capture_rate": self.capture_rate,
        }


@dataclass(frozen=True, slots=True)
class CardSummary:
    held_card_id: str
    fee_due: date | None
    fee_within_warning: bool
    annual_fee: float
    unused_value: float
    used_value_12m: float
    net_value_12m: float
    expiring: tuple[ExpiringItem, ...]
    totals: Totals = field(default_factory=Totals)
    benefit_totals: Mapping[str, Totals] = field(default_factory=dict)
    # Statement freshness, for cards tracked by upload. None when no statement was ever
    # imported: a hand-tracked card has nothing to be overdue.
    last_statement_month: str | None = None  # newest YYYY-MM any statement vouched for
    expected_statement_month: str | None = None  # newest month a statement could cover
    statement_months_behind: int = 0
    statement_due: bool = False


@dataclass(frozen=True, slots=True)
class OwnerSummary:
    owner_id: str
    totals: Totals
    annual_fees: float
    unused_credits: float
    expiring_7d: tuple[ExpiringItem, ...]
    expiring_30d: tuple[ExpiringItem, ...]
    five_24: int
    five_24_items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CardPerksData:
    today: date
    owners: Mapping[str, Owner]
    cards: Mapping[str, HeldCard]
    catalog: Catalog
    instances: Mapping[str, BenefitInstance]
    card_summaries: Mapping[str, CardSummary]
    colors: Mapping[str, str]
    owner_summaries: Mapping[str, OwnerSummary]
    sub_trackers: Mapping[str, SubTracker]
    rotating_activations: Mapping[str, Mapping[str, Mapping[str, str]]]
    perk_values: Mapping[str, Mapping[str, float]]
