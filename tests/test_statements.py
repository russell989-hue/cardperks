"""Statement parsing and the import-statement flow."""

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import CONF_ANNUAL_FEE, CONF_FEE_MONTH, DOMAIN
from custom_components.cardperks.statements import (
    detect_issuer,
    last4_from_filename,
    latest_fee,
    match_credits,
    parse_statement,
)

from .conftest import CARD_ID

CHASE = """Card,Transaction Date,Post Date,Description,Category,Type,Amount,Memo
1234,08/12/2026,08/12/2026,Payment Thank You - Web,,Payment,306.84,
1234,07/22/2026,07/23/2026,TRAVEL CREDIT $300/YEAR,Fees & Adjustments,Adjustment,112.94,
1234,07/22/2026,07/23/2026,AIRBNB * HM43T2NNER,Travel,Sale,-137.50,
1234,07/01/2026,07/01/2026,ANNUAL MEMBERSHIP FEE,Fees & Adjustments,Fee,-450.00,
1234,05/16/2026,05/18/2026,DINING CREDIT $300/YEAR,Fees & Adjustments,Adjustment,150.00,
1234,05/16/2026,05/18/2026,TST*TAVERNETTA,Food & Drink,Sale,-266.40,
1234,03/02/2026,03/03/2026,SOME OTHER CREDIT,Fees & Adjustments,Adjustment,20.00,
1234,02/26/2026,02/27/2026,UA INFLIGHT/INCLUB CREDIT,Fees & Adjustments,Adjustment,1.57,
"""

AMEX = """Date,Description,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category
08/18/2026,UTE SERVICIO AEROBUS,18.00,LOCAL TRANSPORTATION,UTE SERVICIO,,,,SPAIN,'1',Transportation
05/20/2026,RENEWAL MEMBERSHIP FEE,895.00,RENEWAL MEMBERSHIP FEE,RENEWAL MEMBERSHIP FEE,,,,,'2',
05/08/2026,Platinum Resy Credit,-100.00,TST* CARNE,Platinum Resy Credit,,,,,'3',
04/20/2026,AMEX CLEAR PLUS CREDIT,-169.00,CLEAR,AMEX CLEAR PLUS CREDIT,,,,,'4',
"""


def test_detect_and_parse_chase():
    parsed = parse_statement(CHASE, "Chase1234_Activity_20260905.csv")
    assert parsed.issuer == "chase"
    assert parsed.filename_last4 == "1234" and parsed.last4s == {"1234"}
    assert len(parsed.rows) == 8
    fee = latest_fee(parsed)
    assert fee.date == date(2026, 7, 1) and fee.amount == 450.0
    credits = parsed.credit_rows
    assert [round(abs(r.amount), 2) for r in credits] == [112.94, 150.0, 20.0, 1.57]
    assert parsed.date_range == (date(2026, 2, 26), date(2026, 8, 12))


def test_detect_and_parse_amex():
    parsed = parse_statement("﻿" + AMEX, "activity.csv")
    assert parsed.issuer == "amex"
    assert latest_fee(parsed).amount == 895.0 and latest_fee(parsed).date.month == 5
    assert [r.description for r in parsed.credit_rows] == [
        "Platinum Resy Credit",
        "AMEX CLEAR PLUS CREDIT",
    ]


CAPONE = """Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2026-06-18,2026-06-18,6207,CAPITAL ONE AUTOPAY PYMT,Payment/Credit,,2.52
2026-05-23,2026-05-23,6207,INTEREST CHARGE:PURCHASES,Fee/Interest Charge,2.52,
2026-04-07,2026-04-08,6207,APPLE.COM/BILL,Entertainment,,21.02
2026-03-24,2026-03-27,6207,INTEREST CHARGE CREDIT,Payment/Credit,,8.06
2026-03-01,2026-03-02,6207,CAPITAL ONE TRAVEL CREDIT,Payment/Credit,,300.00
2026-02-21,2026-02-21,6207,CAPITAL ONE MEMBER FEE,Fee/Interest Charge,395.00,
2026-02-18,2026-02-19,6207,APPLE.COM/BILL,Entertainment,21.02,
"""


def test_detect_and_parse_capital_one():
    parsed = parse_statement(CAPONE, "2026-09-06_transaction_download.csv")
    assert parsed.issuer == "capital_one" and parsed.last4s == {"6207"}
    fee = latest_fee(parsed)
    assert fee.date == date(2026, 2, 21) and fee.amount == 395.0
    # payments and interest are not credits; a refund with no CREDIT word still counts
    assert [(r.description, abs(r.amount)) for r in parsed.credit_rows] == [
        ("APPLE.COM/BILL", 21.02),
        ("CAPITAL ONE TRAVEL CREDIT", 300.0),
    ]


def test_unknown_format():
    import pytest

    with pytest.raises(ValueError):
        parse_statement("foo,bar\n1,2\n")
    assert detect_issuer(["owner", "product"]) is None
    assert last4_from_filename("Chase1234_Activity_20260905.csv") == "1234"
    assert last4_from_filename("activity (2).csv") is None


def test_match_credits(catalog):
    parsed = parse_statement(CHASE)
    result = match_credits(parsed, catalog.products["test_premium"])
    assert [(m.benefit_id, abs(m.row.amount)) for m in result.matched] == [
        ("travel_credit", 112.94),
        ("dining_credit", 150.0),
    ]
    assert [r.description for r in result.unmatched] == [
        "SOME OTHER CREDIT",
        "UA INFLIGHT/INCLUB CREDIT",
    ]


UUID = "12345678-1234-5678-1234-567812345678"


async def test_import_statement_flow(hass, setup_integration: MockConfigEntry, tmp_path):
    entry = setup_integration
    path = tmp_path / "Chase1234_Activity_20260905.csv"
    path.write_text(CHASE, encoding="utf-8")

    @contextmanager
    def fake_upload(hass_, file_id):
        yield path

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "statement"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    with patch("custom_components.cardperks.config_flow.process_uploaded_file", fake_upload):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"file": UUID}
        )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "card"
    ph = result["description_placeholders"]
    assert ph["issuer"] == "chase" and ph["credits"] == "4" and "450.00" in ph["fee"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": True}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "statement_complete"
    ph = result["description_placeholders"]
    assert "Travel credit: 112.94" in ph["applied"]
    assert "Dining credit: 150.00" in ph["applied"]
    assert "SOME OTHER CREDIT" in ph["unmatched"] and ph["duplicates"] == "0"
    assert "annual fee 450" in ph["fee"]
    await hass.async_block_till_done()

    # Fee override stored on the subentry (card already has an open date, so fee month untouched).
    sub = entry.subentries[CARD_ID]
    assert sub.data[CONF_ANNUAL_FEE] == 450.0 and sub.data.get(CONF_FEE_MONTH) is None

    # Travel credit (cardmember year from 2026-07-01) is current: partial with 112.94 used.
    reg = er.async_get(hass)
    travel = hass.states.get(
        reg.async_get_entity_id("select", DOMAIN, f"{CARD_ID}_travel_credit_status")
    )
    assert travel.state == "partial" and travel.attributes["amount_used"] == 112.94
    # Dining credit on 05/16 fell in the Jan-Jun period, now closed: lands in history.
    doc = entry.runtime_data.doc
    hist = [h for h in doc.history if h.benefit_id == "dining_credit"]
    assert len(hist) == 1 and hist[0].amount_used == 150.0 and hist[0].final_status == "used"
    assert hist[0].closed_by == "statement"
    net = hass.states.get(reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_net_value_12m"))
    assert float(net.state) == round(112.94 + 150.0 - 450.0, 2)

    # Re-import is a no-op.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "statement"), context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.cardperks.config_flow.process_uploaded_file", fake_upload):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"file": UUID}
        )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": False}
    )
    ph = result["description_placeholders"]
    assert ph["duplicates"] == "2" and ph["applied"] == "- none"
    travel = hass.states.get(
        reg.async_get_entity_id("select", DOMAIN, f"{CARD_ID}_travel_credit_status")
    )
    assert travel.attributes["amount_used"] == 112.94


async def test_import_statement_falls_back_to_all_cards(
    hass, setup_integration: MockConfigEntry, tmp_path
):
    """An Amex export with no Amex card configured still lets the user pick a card."""
    entry = setup_integration
    path = tmp_path / "activity.csv"
    path.write_text(AMEX, encoding="utf-8")

    @contextmanager
    def fake_upload(hass_, file_id):
        yield path

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "statement"), context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.cardperks.config_flow.process_uploaded_file", fake_upload):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"file": UUID}
        )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "card"
    assert result["description_placeholders"]["issuer"] == "amex"


async def test_import_statement_unrecognised_file(
    hass, setup_integration: MockConfigEntry, tmp_path
):
    entry = setup_integration
    path = tmp_path / "cards.csv"
    path.write_text("owner,product\nBrian,Premium Card\n", encoding="utf-8")

    @contextmanager
    def fake_upload(hass_, file_id):
        yield path

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "statement"), context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.cardperks.config_flow.process_uploaded_file", fake_upload):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"file": UUID}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unrecognised_statement"}
