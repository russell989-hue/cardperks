"""Bulk CSV import service."""

from datetime import date

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import (
    CONF_FEE_MONTH,
    CONF_LAST4,
    CONF_OPEN_DATE,
    CONF_PARENT_CARD_ID,
    CONF_ROLE,
    DOMAIN,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
)
from custom_components.cardperks.importer import find_product, parse_date, parse_month

from .conftest import CARD_ID

CSV = """owner,issuer,card_product,role,primary_holder_if_AU,open_date,fee_month,last4,nickname
Brian,Test Bank,Premium Card,primary,,2026-07-01,,1234,
Brian,Test Bank,Basic Card,primary,,03/15/2022,,5555,Old Basic
Sam,Test Bank,premium,,,,November,7777,
Nick,testbank,Premium Card,au,Brian,,,,
Nick,Test Bank,Nonexistent Card,primary,,2020-01-01,,,
Sam,Test Bank,Basic Card,primary,,,,,
"""


def test_parse_helpers(catalog):
    assert parse_month("11") == 11 and parse_month("November") == 11 and parse_month("") is None
    assert parse_date("03/15/2022") == date(2022, 3, 15)
    assert parse_date("2022-03") == date(2022, 3, 1)
    with pytest.raises(ValueError):
        parse_date("March 2022")
    assert find_product(catalog, "Test Bank", "premium card").id == "test_premium"
    assert find_product(catalog, "", "test_basic").id == "test_basic"
    assert find_product(catalog, "testbank", "Premium").id == "test_premium"
    assert find_product(catalog, "Other Bank", "Premium Card") is None


async def test_import_cards(hass, setup_integration: MockConfigEntry):
    entry = setup_integration
    resp = await hass.services.async_call(
        DOMAIN, "import_cards", {"csv": CSV}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()

    assert resp["created_owners"] == ["Sam"]
    assert resp["created_cards"] == ["Old Basic", "Premium Card (Sam ·7777)"]
    # Brian ·1234 and the Nick AU card already exist in the fixture entry
    assert len(resp["skipped"]) == 2 and all("already have" in s for s in resp["skipped"])
    assert len(resp["errors"]) == 2
    assert "unknown product" in resp["errors"][0]
    assert "open_date or fee_month" in resp["errors"][1]

    owners = {s.title for s in entry.subentries.values() if s.subentry_type == SUBENTRY_OWNER}
    assert owners == {"Brian", "Nick", "Sam"}
    cards = {s.title: s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CARD}
    assert cards["Old Basic"].data[CONF_OPEN_DATE] == "2022-03-15"
    assert cards["Old Basic"].data[CONF_LAST4] == "5555"
    sam = cards["Premium Card (Sam ·7777)"]
    assert sam.data[CONF_FEE_MONTH] == 11 and sam.data[CONF_OPEN_DATE] is None
    au = cards["Premium Card (AU) (Nick)"]
    assert au.data[CONF_ROLE] == "authorized_user" and au.data[CONF_PARENT_CARD_ID] == CARD_ID

    # entry reloaded once and the new cards have entities
    assert hass.states.get("select.old_basic_sign_up_bonus") is None  # basic has no benefits
    assert hass.states.get("select.premium_card_sam_7777_travel_credit").state == "unused"


async def test_import_bad_header(hass, setup_integration: MockConfigEntry):
    resp = await hass.services.async_call(
        DOMAIN, "import_cards", {"csv": "foo,bar\n1,2\n"}, blocking=True, return_response=True
    )
    assert resp["errors"] and "header" in resp["errors"][0]
    assert not resp["created_cards"]
