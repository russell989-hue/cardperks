"""Write catalog overrides: a product, as JSON, into the user override folder.

Overrides replace a shipped product wholesale, so the file always carries the complete
product, not a patch. That keeps the loader simple and the file readable on its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Benefit, Product

SCHEMA_VERSION = 1


def benefit_to_dict(b: Benefit) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": b.id,
        "name": b.name,
        "type": str(b.type),
        "cadence": str(b.cadence),
        "amount": b.amount,
        "unit": b.unit,
        "reset": str(b.reset),
        "enrollment_required": b.enrollment_required,
        "applies_to": str(b.applies_to),
    }
    if b.default_value is not None:
        out["default_value"] = b.default_value
    if b.expires_days_after_open is not None:
        out["expires_days_after_open"] = b.expires_days_after_open
    if b.spend_required is not None:
        out["spend_required"] = b.spend_required
    if b.notes:
        out["notes"] = b.notes
    if b.statement_match:
        out["statement_match"] = list(b.statement_match)
    if b.conditional:
        out["conditional"] = True
    if b.condition:
        out["condition"] = b.condition
    return out


def product_to_dict(p: Product) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "annual_fee": p.annual_fee,
        "currency": p.currency,
        "default_point_value": p.default_point_value,
        "reports_to_personal_credit": p.reports_to_personal_credit,
        "last_verified": p.last_verified.isoformat(),
        "source_url": p.source_url,
        "needs_verification": p.needs_verification,
        "benefits": [benefit_to_dict(b) for b in p.benefits],
        "earning_rates": [
            {"category": e.category, "multiplier": e.multiplier, "notes": e.notes}
            if e.notes
            else {"category": e.category, "multiplier": e.multiplier}
            for e in p.earning_rates
        ],
        "au_terms": {
            "fee": p.au_terms.fee,
            "own_lounge_access": p.au_terms.own_lounge_access,
            **({"notes": p.au_terms.notes} if p.au_terms.notes else {}),
        },
    }


def write_override(override_dir: Path, product: Product) -> Path:
    """Put `product` into `<override_dir>/<issuer>.json`, replacing any earlier copy.

    Other products already in that file are kept. Returns the file written.
    """
    override_dir.mkdir(parents=True, exist_ok=True)
    path = override_dir / f"{product.issuer}.json"
    data: dict[str, Any]
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {
            "schema_version": SCHEMA_VERSION,
            "issuer": product.issuer,
            "issuer_name": product.issuer_name,
            "products": [],
        }
    products = [p for p in data.get("products", []) if p.get("id") != product.id]
    products.append(product_to_dict(product))
    products.sort(key=lambda p: p["id"])
    data["products"] = products
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
