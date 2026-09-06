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

from .conftest import CARD_ID, OWNER_ID

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
        reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_travel_credit_status")
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
        reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_travel_credit_status")
    )
    assert travel.attributes["amount_used"] == 112.94


async def test_import_statement_creates_the_card(
    hass, setup_integration: MockConfigEntry, tmp_path
):
    """An export with no matching card set up builds the card from the file."""
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
    ph = result["description_placeholders"]
    assert ph["issuer"] == "amex" and "895.00" in ph["fee"]

    # Ask for a new card rather than picking one of the existing ones.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": "__new__", "apply_fee": True}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "new_card"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "owner_id": OWNER_ID,
            "product_id": "test_premium",
            "fee_month": "5",
            "last4": "8888",
        },
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "statement_complete"
    ph = result["description_placeholders"]
    assert "Created the card" in ph["note"] and "8888" in ph["note"]
    await hass.async_block_till_done()

    sub = next(s for s in entry.subentries.values() if s.data.get("last4") == "8888")
    assert sub.data["fee_month"] == 5 and sub.data["product_id"] == "test_premium"
    assert sub.data["annual_fee"] == 895.0  # differs from the catalog's 500
    assert sub.data["role"] == "primary"
    # its entities exist and the fee flows into net value
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id("sensor", DOMAIN, f"{sub.subentry_id}_net_value_12m")
    assert float(hass.states.get(eid).state) == -895.0


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


MULTI = """Card,Transaction Date,Post Date,Description,Category,Type,Amount,Memo
1234,07/22/2026,07/23/2026,TRAVEL CREDIT $300/YEAR,Fees & Adjustments,Adjustment,100.00,
9999,07/22/2026,07/23/2026,TRAVEL CREDIT $300/YEAR,Fees & Adjustments,Adjustment,250.00,
9999,07/01/2026,07/01/2026,ANNUAL MEMBERSHIP FEE,Fees & Adjustments,Fee,-999.00,
1234,07/01/2026,07/01/2026,ANNUAL MEMBERSHIP FEE,Fees & Adjustments,Fee,-450.00,
"""


def test_for_last4_scopes_rows():
    parsed = parse_statement(MULTI)
    assert parsed.last4s == {"1234", "9999"}
    one = parsed.for_last4("1234")
    assert [abs(r.amount) for r in one.credit_rows] == [100.0]
    assert latest_fee(one).amount == 450.0
    assert parsed.other_last4s("1234") == {"9999"}
    # a card number the file does not mention leaves the statement untouched
    assert parsed.for_last4("0000") is parsed
    assert parsed.for_last4(None) is parsed


def test_for_last4_accepts_a_replaced_cards_old_numbers():
    """A stolen card keeps its account; old statements carry the old number."""
    parsed = parse_statement(MULTI)
    both = parsed.for_last4({"1234", "9999"})
    assert sorted(abs(r.amount) for r in both.credit_rows) == [100.0, 250.0]
    assert parsed.other_last4s({"1234", "9999"}) == set()


async def test_multi_card_statement_applies_only_matching_rows(
    hass, setup_integration: MockConfigEntry, tmp_path
):
    """One Chase file covering several cards must not misattribute the other cards' credits."""
    entry = setup_integration
    path = tmp_path / "Chase1234_Activity.csv"
    path.write_text(MULTI, encoding="utf-8")

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
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": False}
    )
    ph = result["description_placeholders"]
    assert "Travel credit: 100.00" in ph["applied"]  # not 250, and not 350
    assert "9999" in ph["note"]
    reg = er.async_get(hass)
    travel = hass.states.get(
        reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_travel_credit_status")
    )
    assert travel.attributes["amount_used"] == 100.0


async def test_statement_adopts_a_replaced_cards_old_number(
    hass, setup_integration: MockConfigEntry, tmp_path
):
    """Numbers in the file matching no card can be claimed as this account's former ones."""
    from custom_components.cardperks.const import CONF_PREVIOUS_LAST4

    entry = setup_integration
    path = tmp_path / "Chase1234_Activity.csv"
    path.write_text(MULTI, encoding="utf-8")

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
    # 9999 belongs to no card, so it is offered for adoption
    assert "adopt_last4" in str(result["data_schema"].schema)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": False, "adopt_last4": ["9999"]}
    )
    assert result["type"] is FlowResultType.ABORT
    ph = result["description_placeholders"]
    assert "9999" in ph["note"] and "earlier numbers" in ph["note"]
    # both the old and the new number's credits land on the one card
    assert "Travel credit: 350.00" in ph["applied"]
    await hass.async_block_till_done()
    assert entry.subentries[CARD_ID].data[CONF_PREVIOUS_LAST4] == ["9999"]


async def test_import_records_coverage(hass, setup_integration: MockConfigEntry, tmp_path):
    """A statement vouches for the months it covers; everything else stays unknown."""
    entry = setup_integration
    path = tmp_path / "Chase1234_Activity_20260905.csv"
    path.write_text(CHASE, encoding="utf-8")

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
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": False}
    )
    await hass.async_block_till_done()

    doc = entry.runtime_data.doc
    # The file spans Feb to Aug 2026, so those months are vouched for and no others.
    assert set(doc.coverage[CARD_ID]) == {
        "2026-02",
        "2026-03",
        "2026-05",
        "2026-07",
        "2026-08",
    }
    assert len(doc.imports) == 1
    rec = doc.imports[0]
    assert rec.issuer == "chase" and rec.rows == 8 and rec.matched == 2
    assert rec.filename == "Chase1234_Activity_20260905.csv"

    reg = er.async_get(hass)
    cov = hass.states.get(reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_coverage_12m"))
    assert cov.state == "5"
    assert "2026-09" in cov.attributes["missing"]  # this month has no statement yet
    assert "2026-08" in cov.attributes["covered"]
    assert cov.attributes["statements_imported"] == 1

    # Re-importing the same file replaces its record instead of stacking a duplicate.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "statement"), context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.cardperks.config_flow.process_uploaded_file", fake_upload):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"file": UUID}
        )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"card": CARD_ID, "apply_fee": False}
    )
    await hass.async_block_till_done()
    assert len(entry.runtime_data.doc.imports) == 1
