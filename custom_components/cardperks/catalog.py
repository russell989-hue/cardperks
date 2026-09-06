"""Catalog loading: shipped JSON per issuer plus user override files."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import voluptuous as vol

from .const import AppliesTo, BenefitType, Cadence, ResetRule
from .models import AuTerms, Benefit, Catalog, CatalogProblem, EarningRate, Product

_LOGGER = logging.getLogger(__name__)

SHIPPED_DIR = Path(__file__).parent / "catalog"


def _iso_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as err:
        raise vol.Invalid(f"invalid date {value!r}") from err


BENEFIT_SCHEMA = vol.Schema(
    {
        vol.Required("id"): vol.All(str, vol.Match(r"^[a-z0-9_]+$")),
        vol.Required("name"): str,
        vol.Required("type"): vol.Coerce(BenefitType),
        vol.Required("cadence"): vol.Coerce(Cadence),
        vol.Required("amount"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("unit", default="USD"): str,
        vol.Optional("reset", default="calendar"): vol.Coerce(ResetRule),
        vol.Optional("enrollment_required", default=False): bool,
        vol.Optional("applies_to", default="primary"): vol.Coerce(AppliesTo),
        vol.Optional("default_value"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("expires_days_after_open"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("spend_required"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("notes"): vol.Any(None, str),
        vol.Optional("statement_match", default=list): [str],
    }
)

EARNING_SCHEMA = vol.Schema(
    {
        vol.Required("category"): str,
        vol.Required("multiplier"): vol.Coerce(float),
        vol.Optional("notes"): vol.Any(None, str),
    }
)

AU_TERMS_SCHEMA = vol.Schema(
    {
        vol.Optional("fee", default=0.0): vol.Coerce(float),
        vol.Optional("own_lounge_access", default=False): bool,
        vol.Optional("notes"): vol.Any(None, str),
    }
)

PRODUCT_SCHEMA = vol.Schema(
    {
        vol.Required("id"): vol.All(str, vol.Match(r"^[a-z0-9_]+$")),
        vol.Required("name"): str,
        vol.Required("annual_fee"): vol.Coerce(float),
        vol.Optional("currency", default="points"): str,
        vol.Optional("default_point_value", default=0.01): vol.Coerce(float),
        vol.Optional("reports_to_personal_credit", default=True): bool,
        vol.Required("last_verified"): _iso_date,
        vol.Required("source_url"): str,
        vol.Optional("needs_verification", default=False): bool,
        vol.Optional("benefits", default=list): [BENEFIT_SCHEMA],
        vol.Optional("earning_rates", default=list): [EARNING_SCHEMA],
        vol.Optional("au_terms", default=dict): AU_TERMS_SCHEMA,
    }
)

FILE_SCHEMA = vol.Schema(
    {
        vol.Optional("schema_version", default=1): 1,
        vol.Required("issuer"): vol.All(str, vol.Match(r"^[a-z0-9_]+$")),
        vol.Required("issuer_name"): str,
        vol.Required("products"): [PRODUCT_SCHEMA],
    }
)


def _build_product(raw: dict[str, Any], issuer: str, issuer_name: str, origin: str) -> Product:
    benefits = tuple(
        Benefit(
            id=b["id"],
            name=b["name"],
            type=b["type"],
            cadence=b["cadence"],
            amount=b["amount"],
            unit=b["unit"],
            reset=b["reset"],
            enrollment_required=b["enrollment_required"],
            applies_to=b["applies_to"],
            default_value=b.get("default_value"),
            expires_days_after_open=b.get("expires_days_after_open"),
            spend_required=b.get("spend_required"),
            notes=b.get("notes"),
            statement_match=tuple(b.get("statement_match", [])),
        )
        for b in raw["benefits"]
    )
    seen: set[str] = set()
    for b in benefits:
        if b.id in seen:
            raise vol.Invalid(f"product {raw['id']}: duplicate benefit id {b.id}")
        seen.add(b.id)
        if b.amount is None and b.type not in (BenefitType.PERK, BenefitType.INSURANCE):
            raise vol.Invalid(f"benefit {b.id}: amount may be null only for perk/insurance")
    return Product(
        id=raw["id"],
        issuer=issuer,
        issuer_name=issuer_name,
        name=raw["name"],
        annual_fee=raw["annual_fee"],
        currency=raw["currency"],
        default_point_value=raw["default_point_value"],
        reports_to_personal_credit=raw["reports_to_personal_credit"],
        last_verified=raw["last_verified"],
        source_url=raw["source_url"],
        benefits=benefits,
        earning_rates=tuple(
            EarningRate(category=e["category"], multiplier=e["multiplier"], notes=e.get("notes"))
            for e in raw["earning_rates"]
        ),
        au_terms=AuTerms(
            fee=raw["au_terms"]["fee"],
            own_lounge_access=raw["au_terms"]["own_lounge_access"],
            notes=raw["au_terms"].get("notes"),
        ),
        needs_verification=raw["needs_verification"],
        origin=origin,
    )


def _load_file(path: Path, origin: str) -> list[Product]:
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    data = FILE_SCHEMA(raw)
    return [
        _build_product(p, data["issuer"], data["issuer_name"], origin) for p in data["products"]
    ]


def load_catalog(
    shipped_dir: Path | str = SHIPPED_DIR, override_dir: Path | str | None = None
) -> tuple[Catalog, list[CatalogProblem]]:
    """Load shipped catalog files, then apply overrides. Never raises on override errors."""
    products: dict[str, Product] = {}
    problems: list[CatalogProblem] = []

    for path in sorted(Path(shipped_dir).glob("*.json")):
        for p in _load_file(path, "shipped"):  # shipped files must be valid
            products[p.id] = p

    if override_dir:
        odir = Path(override_dir)
        if odir.is_dir():
            for path in sorted(odir.glob("*.json")):
                try:
                    for p in _load_file(path, str(path)):
                        products[p.id] = p
                except (OSError, ValueError, vol.Invalid) as err:
                    _LOGGER.warning("Skipping catalog override %s: %s", path, err)
                    problems.append(CatalogProblem(path=str(path), message=str(err)))

    return Catalog(products=products), problems
