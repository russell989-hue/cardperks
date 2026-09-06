"""Catalog loading, overrides, and the shipped data itself."""

import json
from datetime import date
from pathlib import Path

from homeassistant.helpers import issue_registry as ir

from custom_components.cardperks.catalog import SHIPPED_DIR, load_catalog
from custom_components.cardperks.const import DOMAIN, BenefitType
from custom_components.cardperks.repairs import async_check_catalog_issues

from .conftest import FIXTURE_CATALOG


def test_fixture_catalog_loads(catalog):
    assert set(catalog.products) == {"test_premium", "test_basic"}
    p = catalog.products["test_premium"]
    assert p.annual_fee == 500 and p.last_verified == date(2026, 8, 1)
    assert p.benefit("lounge").type is BenefitType.PERK
    assert catalog.issuers() == {"testbank": "Test Bank"}


def test_shipped_catalog_is_valid():
    catalog, problems = load_catalog(SHIPPED_DIR)
    assert not problems
    assert {
        "chase_sapphire_reserve",
        "chase_ink_business_preferred",
        "chase_southwest_plus",
        "chase_united_explorer",
        "chase_united_club",
        "amex_platinum",
        "capital_one_venture_x",
    } <= set(catalog.products)
    for p in catalog.products.values():
        assert p.source_url.startswith("https://")
        assert p.benefits, p.id


def test_override_replaces_product(tmp_path: Path):
    override = {
        "issuer": "testbank",
        "issuer_name": "Test Bank",
        "products": [
            {
                "id": "test_basic",
                "name": "Basic Card v2",
                "annual_fee": 5,
                "last_verified": "2026-09-01",
                "source_url": "https://example.com/basic2",
                "benefits": [],
            },
            {
                "id": "test_new",
                "name": "New Card",
                "annual_fee": 0,
                "last_verified": "2026-09-01",
                "source_url": "https://example.com/new",
            },
        ],
    }
    (tmp_path / "mine.json").write_text(json.dumps(override))
    catalog, problems = load_catalog(FIXTURE_CATALOG, tmp_path)
    assert not problems
    assert catalog.products["test_basic"].name == "Basic Card v2"
    assert catalog.products["test_basic"].origin.endswith("mine.json")
    assert "test_new" in catalog.products
    assert catalog.products["test_premium"].origin == "shipped"


def test_bad_override_is_skipped_and_reported(tmp_path: Path):
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "invalid.json").write_text(
        json.dumps({"issuer": "x", "issuer_name": "X", "products": [{"id": "bad", "name": "Bad"}]})
    )
    catalog, problems = load_catalog(FIXTURE_CATALOG, tmp_path)
    assert set(catalog.products) == {"test_premium", "test_basic"}
    assert {Path(p.path).name for p in problems} == {"broken.json", "invalid.json"}


def test_missing_override_dir_is_fine(tmp_path: Path):
    catalog, problems = load_catalog(FIXTURE_CATALOG, tmp_path / "nope")
    assert not problems and len(catalog.products) == 2


async def test_repair_issues(hass, catalog):
    from custom_components.cardperks.models import CatalogProblem

    async_check_catalog_issues(hass, catalog, [CatalogProblem(path="/x/y.json", message="boom")])
    registry = ir.async_get(hass)
    # test_basic was verified 2025-01-01, more than 183 days before 2026-09-05
    assert registry.async_get_issue(DOMAIN, "stale_catalog_test_basic") is not None
    assert registry.async_get_issue(DOMAIN, "stale_catalog_test_premium") is None
    assert registry.async_get_issue(DOMAIN, "catalog_needs_verification") is None
    assert any(i.issue_id.startswith("invalid_override_") for i in registry.issues.values())
