"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.catalog import load_catalog
from custom_components.cardperks.const import (
    CONF_CLOSE_DATE,
    CONF_FEE_MONTH,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_NOTES,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PRODUCT_ID,
    CONF_ROLE,
    DOMAIN,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
)
from custom_components.cardperks.models import Catalog

FIXTURE_CATALOG = Path(__file__).parent / "fixtures" / "catalog"
TODAY = date(2026, 9, 5)

OWNER_ID = "owner_brian"
CARD_ID = "card_premium_1"
AU_CARD_ID = "card_premium_au"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Required for custom components under pytest-homeassistant-custom-component."""


@pytest.fixture(autouse=True)
def fixture_catalog_dir() -> Generator[None]:
    with patch("custom_components.cardperks.helpers.SHIPPED_DIR", FIXTURE_CATALOG):
        yield


@pytest.fixture(autouse=True)
def frozen_today(freezer):
    freezer.move_to("2026-09-05 10:00:00+00:00")
    return freezer


@pytest.fixture
def catalog() -> Catalog:
    cat, problems = load_catalog(FIXTURE_CATALOG)
    assert not problems
    return cat


def owner_subentry(name: str = "Brian", subentry_id: str = OWNER_ID) -> dict:
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_OWNER,
        "title": name,
        "unique_id": name.lower(),
        "data": {CONF_NAME: name},
    }


def card_subentry(
    subentry_id: str = CARD_ID,
    owner_id: str = OWNER_ID,
    product_id: str = "test_premium",
    role: str = "primary",
    parent_card_id: str | None = None,
    open_date: str | None = "2026-07-01",
    fee_month: int | None = None,
    last4: str | None = "1234",
    nickname: str | None = None,
    title: str = "Premium Card (Brian | 1234)",
) -> dict:
    return {
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_CARD,
        "title": title,
        "unique_id": None,
        "data": {
            CONF_OWNER_ID: owner_id,
            CONF_PRODUCT_ID: product_id,
            CONF_ROLE: role,
            CONF_PARENT_CARD_ID: parent_card_id,
            CONF_OPEN_DATE: open_date,
            CONF_FEE_MONTH: fee_month,
            CONF_LAST4: last4,
            CONF_NICKNAME: nickname,
            CONF_NOTES: None,
            CONF_CLOSE_DATE: None,
        },
    }


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={},
        entry_id="cardperks_entry",
        subentries_data=[
            owner_subentry(),
            card_subentry(),
            card_subentry(
                subentry_id=AU_CARD_ID,
                owner_id="owner_nick",
                role="authorized_user",
                parent_card_id=CARD_ID,
                last4=None,
                title="Premium Card (AU) (Nick)",
            ),
            owner_subentry("Nick", "owner_nick"),
        ],
    )


@pytest.fixture
async def setup_integration(hass, mock_entry: MockConfigEntry) -> AsyncGenerator[MockConfigEntry]:
    await hass.config.async_set_time_zone("UTC")
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    yield mock_entry
