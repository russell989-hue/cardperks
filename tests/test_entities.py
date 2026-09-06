"""Entity states, services, and persistence."""

import pathlib
from datetime import date

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN, STORAGE_KEY
from custom_components.cardperks.models import HistoryRecord

from .conftest import AU_CARD_ID, CARD_ID, OWNER_ID


def _eid(hass, platform: str, unique_id: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert eid, unique_id
    return eid


async def test_entities_created(hass, setup_integration: MockConfigEntry):
    registry = er.async_get(hass)
    ours = [e for e in registry.entities.values() if e.platform == DOMAIN]
    # Per benefit: expires + remaining + status sensors, a mark-used button, a dollars-used
    # number where it has a dollar amount, and a value number for perks.
    #   monthly/dining/travel 5 each, lounge 6, sign-up bonus 4 (points, so no dollar box) = 25
    # Card-level: fee due, unused, net, annual value, captured, forfeited, capture rate,
    # fee-within-45d, statement-due = 9. Owners: 4 rollups + 3 dollar totals = 7 each.
    # ...plus a colour select and a statement-coverage sensor per card.
    # The uncapped inflight rebate gets a status sensor only.
    # ...plus Priority Pass, shared: 5 entities on each card and one household number.
    # ...plus a status sensor per card for the status the lounge perk grants.
    assert len(ours) == (25 + 5 + 1 + 10 + 1 + 1) + (6 + 5 + 10 + 1 + 1) + (7 * 2) + 1

    travel = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_travel_credit_status"))
    assert travel.state == "unused"
    assert travel.attributes["amount"] == 300 and travel.attributes["period_end"] == "2027-06-30"
    assert travel.attributes["kind"] == "benefit_status" and travel.attributes["card_id"] == CARD_ID
    assert travel.name == "Premium Card (Brian | 1234) Travel credit status"

    expires = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_expires"))
    assert expires.state == "2026-12-31" and expires.attributes["days_left"] == 117

    fee = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_fee_due"))
    assert fee.state == "2027-07-01" and fee.attributes["kind"] == "fee_due"
    assert hass.states.get(_eid(hass, "binary_sensor", f"{CARD_ID}_fee_within_45d")).state == "off"

    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 150.0 and rem.attributes["percent_used"] == 0.0
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_sub_remaining")).state == "unknown"

    unused = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value"))
    assert float(unused.state) == 10 + 150 + 300 + 100  # sub has no dollar amount
    rate = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_capture_rate"))
    assert rate.attributes["open_remaining"] == 560.0 and rate.attributes["unknown_12m"] == 0.0
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    assert float(net.state) == -500

    # AU device only has lounge, and hangs off the primary card
    dev_reg = dr.async_get(hass)
    au_dev = dev_reg.async_get_device_by_identifier(
        (DOMAIN, AU_CARD_ID), setup_integration.entry_id
    )
    primary_dev = dev_reg.async_get_device_by_identifier(
        (DOMAIN, CARD_ID), setup_integration.entry_id
    )
    assert au_dev.via_device_id == primary_dev.id
    assert primary_dev.manufacturer == "Test Bank" and primary_dev.model == "Premium Card"
    assert hass.states.get(_eid(hass, "sensor", f"{AU_CARD_ID}_lounge_status")).state == "unused"
    assert (
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{AU_CARD_ID}_travel_credit_status"
        )
        is None
    )

    # owner rollups
    assert (
        float(hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_unused_credits")).state)
        == 560
    )
    exp30 = hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_expiring_30d"))
    assert exp30.state == "1"  # September monthly credit
    assert exp30.attributes["items"][0]["benefit"] == "Monthly credit (monthly)"
    assert hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_expiring_7d")).state == "0"
    five = hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_5_24"))
    assert five.state == "1" and five.attributes["under_5_24"] is True


async def test_select_and_button_and_services(
    hass, setup_integration: MockConfigEntry, hass_storage
):
    dining = _eid(hass, "sensor", f"{CARD_ID}_dining_credit_status")

    dining_used = _eid(hass, "number", f"{CARD_ID}_dining_credit_used")
    await hass.services.async_call(
        "number", "set_value", {"entity_id": dining_used, "value": 150}, blocking=True
    )
    st = hass.states.get(dining)
    assert st.state == "used" and st.attributes["amount_used"] == 150
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == 410
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m")).state) == -350

    await hass.services.async_call(
        DOMAIN, "reset_benefit", {"entity_id": dining_used}, blocking=True
    )
    assert hass.states.get(dining).state == "unused"

    await hass.services.async_call(
        DOMAIN, "mark_used", {"entity_id": dining_used, "amount": 40, "note": "Resy"}, blocking=True
    )
    st = hass.states.get(dining)
    assert st.state == "partial" and st.attributes["amount_used"] == 40
    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 110.0 and rem.attributes["percent_used"] == 26.7
    assert hass.states.get(dining_used).attributes["uses"][0]["note"] == "Resy"
    await hass.services.async_call(DOMAIN, "mark_used", {"entity_id": dining_used}, blocking=True)
    assert hass.states.get(dining).state == "used"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _eid(hass, "button", f"{CARD_ID}_monthly_credit_mark_used")},
        blocking=True,
    )
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_monthly_credit_status")).state == "used"

    # "not applicable" is card configuration now, not a per-period status.
    sub = setup_integration.subentries[CARD_ID]
    hass.config_entries.async_update_subentry(
        setup_integration, sub, data={**sub.data, "not_applicable": ["lounge"]}
    )
    await hass.async_block_till_done()

    # persisted
    await hass.async_block_till_done()
    from homeassistant.helpers.storage import Store

    data = hass_storage.get(STORAGE_KEY)
    if data is None:  # delayed save not flushed yet; force it
        await setup_integration.runtime_data.store.async_save_document(
            setup_integration.runtime_data.doc
        )
        data = hass_storage[STORAGE_KEY]
    inst = data["data"]["benefit_instances"][f"{CARD_ID}:dining_credit"]
    assert inst["status"] == "used" and inst["amount_used"] == 150
    lounge = setup_integration.runtime_data.doc.instances[f"{CARD_ID}:lounge"]
    assert lounge.sticky_na is True and str(lounge.status) == "n_a"
    assert isinstance(Store, type)


async def test_device_services(hass, setup_integration: MockConfigEntry):
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, CARD_ID), setup_integration.entry_id
    )
    owner_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"owner:{OWNER_ID}"), setup_integration.entry_id
    )

    await hass.services.async_call(
        DOMAIN,
        "set_perk_value",
        {"device_id": device.id, "benefit_id": "lounge", "value": 250},
        blocking=True,
    )
    lounge = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_lounge_status"))
    assert lounge.attributes["amount"] == 250
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == 710

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_perk_value",
            {"device_id": device.id, "benefit_id": "travel_credit", "value": 1},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_perk_value",
            {"device_id": owner_device.id, "benefit_id": "lounge", "value": 1},
            blocking=True,
        )

    await hass.services.async_call(
        DOMAIN, "add_sub_spend", {"device_id": device.id, "amount": 1500}, blocking=True
    )
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    tracker = net.attributes["sub_tracker"]
    assert (
        tracker["required"] == 4000 and tracker["spent"] == 1500 and tracker["completed_on"] is None
    )
    await hass.services.async_call(
        DOMAIN, "add_sub_spend", {"device_id": device.id, "amount": 2600}, blocking=True
    )
    net = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m"))
    assert net.attributes["sub_tracker"]["completed_on"] == date(2026, 9, 5).isoformat()
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_sub_status")).state == "used"

    await hass.services.async_call(
        DOMAIN,
        "activate_rotating_category",
        {"device_id": device.id, "category": "gas"},
        blocking=True,
    )
    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_dining_credit_remaining"))
    assert float(rem.state) == 150.0 and rem.attributes["percent_used"] == 0.0
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_sub_remaining")).state == "unknown"

    unused = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value"))
    assert unused.attributes["rotating_activations"]["2026-Q3"]["category"] == "gas"


async def test_annual_fee_override(hass, mock_entry: MockConfigEntry):
    from custom_components.cardperks.const import CONF_ANNUAL_FEE

    sub = mock_entry.subentries[CARD_ID]
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_subentry(
        mock_entry, sub, data={**sub.data, CONF_ANNUAL_FEE: 450}
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    fee = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_fee_due"))
    assert fee.attributes["annual_fee"] == 450
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_net_value_12m")).state) == -450


async def test_state_survives_reload(hass, setup_integration: MockConfigEntry):
    dining = _eid(hass, "sensor", f"{CARD_ID}_dining_credit_status")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, "number", f"{CARD_ID}_dining_credit_used"), "value": 150},
        blocking=True,
    )
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(dining).state == "used"


async def test_catalog_change_removes_stale_entities(
    hass, setup_integration: MockConfigEntry, tmp_path, monkeypatch
):
    """A benefit that stops applying to authorized users loses its entities and instance."""
    import json
    import shutil

    from custom_components.cardperks.const import BenefitStatus

    entry = setup_integration
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{AU_CARD_ID}_lounge_status")
    assert f"{AU_CARD_ID}:lounge" in entry.runtime_data.doc.instances
    entry.runtime_data.set_status(AU_CARD_ID, "lounge", BenefitStatus.USED)

    # Rewrite the fixture catalog so the lounge perk is primary-only.
    src = pathlib.Path(__file__).parent / "fixtures" / "catalog"
    dst = tmp_path / "catalog"
    shutil.copytree(src, dst)
    f = dst / "test_issuer.json"
    data = json.loads(f.read_text())
    for prod in data["products"]:
        for b in prod["benefits"]:
            if b["id"] == "lounge":
                b["applies_to"] = "primary"
    f.write_text(json.dumps(data))
    monkeypatch.setattr("custom_components.cardperks.helpers.SHIPPED_DIR", dst)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert reg.async_get_entity_id("sensor", DOMAIN, f"{AU_CARD_ID}_lounge_status") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{AU_CARD_ID}_lounge_remaining") is None
    # The primary keeps it, and the AU instance is closed into history, not silently dropped.
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_lounge_status")
    doc = entry.runtime_data.doc
    assert f"{AU_CARD_ID}:lounge" not in doc.instances
    closed = [h for h in doc.history if h.held_card_id == AU_CARD_ID and h.benefit_id == "lounge"]
    assert len(closed) == 1 and closed[0].closed_by == "not_applicable"
    assert closed[0].final_status == "used"


async def test_conditional_benefit_is_off_until_enabled(hass, mock_entry: MockConfigEntry):
    """Conditional benefits only exist for cards whose holder says they qualify."""
    from custom_components.cardperks.const import CONF_ENABLED_CONDITIONAL

    mock_entry.add_to_hass(hass)
    await hass.config.async_set_time_zone("UTC")
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    reg = er.async_get(hass)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_status_bonus_status") is None
    assert f"{CARD_ID}:status_bonus" not in mock_entry.runtime_data.doc.instances
    baseline = float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state)

    sub = mock_entry.subentries[CARD_ID]
    hass.config_entries.async_update_subentry(
        mock_entry, sub, data={**sub.data, CONF_ENABLED_CONDITIONAL: ["status_bonus"]}
    )
    await hass.async_block_till_done()

    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_status_bonus_status")).state == "unused"
    rem = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_status_bonus_remaining"))
    assert float(rem.state) == 200.0
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == (
        baseline + 200.0
    )

    # Turning it back off removes the entities and closes the instance.
    sub = mock_entry.subentries[CARD_ID]
    hass.config_entries.async_update_subentry(
        mock_entry, sub, data={**sub.data, CONF_ENABLED_CONDITIONAL: []}
    )
    await hass.async_block_till_done()
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_status_bonus_status") is None
    doc = mock_entry.runtime_data.doc
    assert f"{CARD_ID}:status_bonus" not in doc.instances
    assert any(
        h.benefit_id == "status_bonus" and h.closed_by == "not_applicable" for h in doc.history
    )


async def test_perk_value_number(hass, setup_integration: MockConfigEntry):
    """Perk values are typable, persist, and feed the money rollups."""
    num = _eid(hass, "number", f"{CARD_ID}_lounge_value")
    st = hass.states.get(num)
    assert float(st.state) == 100.0
    assert st.attributes["catalog_default"] == 100 and st.attributes["customised"] is False
    baseline = float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state)

    await hass.services.async_call(
        "number", "set_value", {"entity_id": num, "value": 250}, blocking=True
    )
    st = hass.states.get(num)
    assert float(st.state) == 250.0 and st.attributes["customised"] is True
    assert (
        float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_lounge_remaining")).state) == 250.0
    )
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_unused_value")).state) == (
        baseline + 150.0
    )

    # Statement credits keep their issuer amount and get no number entity.
    assert (
        er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{CARD_ID}_dining_credit_value")
        is None
    )

    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(num).state) == 250.0


def test_all_last4_covers_replacements():
    from custom_components.cardperks.const import Role
    from custom_components.cardperks.models import HeldCard

    card = HeldCard(
        id="c1",
        owner_id="o1",
        product_id="p",
        role=Role.PRIMARY,
        title="t",
        last4="1111",
        previous_last4=("2222", "3333"),
    )
    assert card.all_last4 == frozenset({"1111", "2222", "3333"})
    bare = HeldCard(id="c2", owner_id="o1", product_id="p", role=Role.PRIMARY, title="t")
    assert bare.all_last4 == frozenset()


async def test_annual_dollars_captured_and_forfeited(hass, setup_integration: MockConfigEntry):
    """The dollar frame: a year's worth, what was captured, and what was lost."""
    entry = setup_integration
    coord = entry.runtime_data

    # $10 monthly = $120 a year; $150 semiannual = $300; $300 annual = $300; lounge perk $100.
    annual = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_annual_value"))
    assert float(annual.state) == 120 + 300 + 300 + 100

    # Capture half of this month's credit.
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _eid(hass, "number", f"{CARD_ID}_monthly_credit_used"), "value": 4},
        blocking=True,
    )
    captured = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_captured_12m"))
    assert float(captured.state) == 4.0

    # A month that closed unused is money gone, not money pending.
    coord.doc.history.append(
        HistoryRecord(
            held_card_id=CARD_ID,
            benefit_id="monthly_credit",
            period_start="2026-08-01",
            period_end="2026-08-31",
            final_status="unused",
            amount=10.0,
            amount_used=0.0,
            closed_at="2026-09-01T00:05:00+00:00",
            closed_by="rollover",
        )
    )
    # An imported gap has no usage evidence, so it is unknown rather than assumed lost.
    coord.doc.history.append(
        HistoryRecord(
            held_card_id=CARD_ID,
            benefit_id="monthly_credit",
            period_start="2026-07-01",
            period_end="2026-07-31",
            final_status="unknown",
            amount=10.0,
            amount_used=0.0,
            closed_at="2026-08-01T00:05:00+00:00",
            closed_by="gap",
        )
    )
    coord.commit()
    await hass.async_block_till_done()

    forfeited = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_forfeited_12m"))
    assert float(forfeited.state) == 10.0
    assert forfeited.attributes["unknown_12m"] == 10.0
    rate = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_capture_rate"))
    assert float(rate.state) == round(4 / 820 * 100, 1)

    # Owner rollups add the cards up.
    owner_annual = hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_annual_value"))
    assert float(owner_annual.state) == 820.0
    assert hass.states.get(_eid(hass, "sensor", f"owner_{OWNER_ID}_forfeited_12m")).state == "10.0"


async def test_forfeited_consults_statement_coverage(hass, setup_integration: MockConfigEntry):
    """Once statements are the evidence, a month nobody imported is unknown, not lost.

    Before any statement exists the card is tracked by hand and an unused close is
    forfeited. After the first import, a closed statement-credit period is only
    forfeited when a statement covered every month of it. Perks never appear on a
    statement, so they keep the manual rule either way.
    """
    entry = setup_integration
    coord = entry.runtime_data

    def closed(benefit_id: str, start: str, end: str, amount: float, used: float = 0.0):
        return HistoryRecord(
            held_card_id=CARD_ID,
            benefit_id=benefit_id,
            period_start=start,
            period_end=end,
            final_status="partial" if used else "unused",
            amount=amount,
            amount_used=used,
            closed_at="2026-09-01T00:05:00+00:00",
            closed_by="rollover",
        )

    coord.doc.history.extend(
        [
            closed("monthly_credit", "2026-08-01", "2026-08-31", 10.0),  # covered below
            closed("monthly_credit", "2026-06-01", "2026-06-30", 10.0),  # never imported
            # Semiannual, Jan-Jun: statements for some months, so $150 - $40 cannot be judged.
            closed("dining_credit", "2026-01-01", "2026-06-30", 150.0, used=40.0),
            # A perk is a lounge visit, not a statement line: still forfeited when unused.
            closed("lounge", "2025-07-01", "2026-06-30", 100.0),
        ]
    )
    coord.commit()
    await hass.async_block_till_done()

    # No statement yet: every unused close is forfeited, as before.
    forfeited = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_forfeited_12m"))
    assert float(forfeited.state) == 10 + 10 + 110 + 100
    assert forfeited.attributes["unknown_12m"] == 0.0

    # One statement vouches for Jan, Feb and Aug.
    coord.record_import(
        CARD_ID,
        file_hash="abc123def456",
        filename="statement.csv",
        issuer="chase",
        months={"2026-01", "2026-02", "2026-08"},
        first_date="2026-01-03",
        last_date="2026-08-30",
        rows=3,
        credit_rows=0,
        matched=0,
        applied=0.0,
    )
    coord.commit()
    await hass.async_block_till_done()

    forfeited = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_forfeited_12m"))
    # August was covered and unused: forfeited. June was never imported: unknown.
    # Dining ran Jan-Jun with only two months covered: the $110 left is unknown.
    # The lounge perk is unaffected by statements.
    assert float(forfeited.state) == 10 + 100
    assert forfeited.attributes["unknown_12m"] == 10 + 110
    per = coord.data.card_summaries[CARD_ID].benefit_totals
    assert per["monthly_credit"].forfeited == 10.0 and per["monthly_credit"].unknown == 10.0
    assert per["dining_credit"].forfeited == 0.0 and per["dining_credit"].unknown == 110.0
    assert per["dining_credit"].captured == 40.0
    assert per["lounge"].forfeited == 100.0 and per["lounge"].unknown == 0.0

    # Importing the missing month settles it: June really was unused.
    coord.record_import(
        CARD_ID,
        file_hash="fedcba654321",
        filename="june.csv",
        issuer="chase",
        months={"2026-06"},
        first_date="2026-06-02",
        last_date="2026-06-29",
        rows=1,
        credit_rows=0,
        matched=0,
        applied=0.0,
    )
    coord.commit()
    await hass.async_block_till_done()
    forfeited = hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_forfeited_12m"))
    assert float(forfeited.state) == 10 + 10 + 100
    assert forfeited.attributes["unknown_12m"] == 110.0


async def test_statement_due_reminder(hass, setup_integration: MockConfigEntry):
    """A card tracked by upload is nagged when its statements fall behind, and only then.

    Today is 2026-09-05, so the newest month a statement could cover is August. One
    month of grace means July is fine and June is overdue. A card with no statements at
    all is never overdue: it is tracked by hand.
    """
    entry = setup_integration
    coord = entry.runtime_data
    registry = ir.async_get(hass)
    eid = _eid(hass, "binary_sensor", f"{CARD_ID}_statement_due")

    due = hass.states.get(eid)
    assert due.state == "off" and due.attributes["last_statement_month"] is None
    assert registry.async_get_issue(DOMAIN, f"statement_due_{CARD_ID}") is None

    def imported(file_hash: str, months: set[str]) -> None:
        coord.record_import(
            CARD_ID,
            file_hash=file_hash,
            filename=f"{file_hash}.csv",
            issuer="chase",
            months=months,
            first_date=None,
            last_date=None,
            rows=1,
            credit_rows=0,
            matched=0,
            applied=0.0,
        )
        coord.commit()

    imported("aaaaaaaaaaaa", {"2026-05", "2026-06"})
    await hass.async_block_till_done()
    due = hass.states.get(eid)
    assert due.state == "on"
    assert due.attributes["last_statement_month"] == "2026-06"
    assert due.attributes["expected_statement_month"] == "2026-08"
    assert due.attributes["months_behind"] == 2
    issue = registry.async_get_issue(DOMAIN, f"statement_due_{CARD_ID}")
    assert issue is not None and issue.translation_placeholders["months"] == "2"

    # July arrives: within grace, so the nag clears at once.
    imported("bbbbbbbbbbbb", {"2026-07"})
    await hass.async_block_till_done()
    due = hass.states.get(eid)
    assert due.state == "off" and due.attributes["months_behind"] == 1
    assert registry.async_get_issue(DOMAIN, f"statement_due_{CARD_ID}") is None

    # The AU card never had a statement and stays quiet.
    au = hass.states.get(_eid(hass, "binary_sensor", f"{AU_CARD_ID}_statement_due"))
    assert au.state == "off" and au.attributes["last_statement_month"] is None


async def test_not_applicable_leaves_the_totals(hass, setup_integration: MockConfigEntry):
    """A benefit you cannot use should not be counted as annual value or as forfeited."""
    entry = setup_integration
    before = float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_annual_value")).state)
    sub = entry.subentries[CARD_ID]
    hass.config_entries.async_update_subentry(
        entry, sub, data={**sub.data, "not_applicable": ["travel_credit"]}
    )
    await hass.async_block_till_done()
    after = float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_annual_value")).state)
    assert after == before - 300
    assert hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_travel_credit_status")).state == "n_a"


async def test_card_colour_from_form_flows_to_entities(hass, setup_integration: MockConfigEntry):
    """Colour is set once in the card form; every entity of the card reports it live."""
    entry = setup_integration
    fee = _eid(hass, "sensor", f"{CARD_ID}_fee_due")
    au_fee = _eid(hass, "sensor", f"{AU_CARD_ID}_fee_due")
    first = hass.states.get(fee).attributes["color"]
    second = hass.states.get(au_fee).attributes["color"]
    assert first and second and first != second  # distinct palette slots by default

    sub = entry.subentries[CARD_ID]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "color": "amber"})
    await hass.async_block_till_done()
    assert hass.states.get(fee).attributes["color"] == "amber"
    assert (
        hass.states.get(_eid(hass, "number", f"{CARD_ID}_dining_credit_used")).attributes["color"]
        == "amber"
    )
    # no colour dropdown entity any more
    assert er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{CARD_ID}_color") is None


async def test_card_status_freezes_and_cancels(hass, setup_integration: MockConfigEntry):
    """Frozen and cancelled cards stop tracking and drop out of every total."""
    entry = setup_integration
    status = _eid(hass, "select", f"{CARD_ID}_status")
    assert hass.states.get(status).state == "active"
    owner_unused = _eid(hass, "sensor", f"owner_{OWNER_ID}_unused_credits")
    owner_annual = _eid(hass, "sensor", f"owner_{OWNER_ID}_annual_value")
    assert float(hass.states.get(owner_unused).state) > 0

    await hass.services.async_call(
        "select", "select_option", {"entity_id": status, "option": "frozen"}, blocking=True
    )
    assert hass.states.get(status).state == "frozen"
    assert (
        hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_fee_due")).attributes["card_status"]
        == "frozen"
    )
    # open periods were closed into history and the card no longer counts
    doc = entry.runtime_data.doc
    assert not any(k.startswith(f"{CARD_ID}:") for k in doc.instances)
    assert any(h.held_card_id == CARD_ID and h.closed_by == "frozen" for h in doc.history)
    assert float(hass.states.get(owner_unused).state) == 0.0
    assert float(hass.states.get(owner_annual).state) == 0.0
    assert float(hass.states.get(_eid(hass, "sensor", f"{CARD_ID}_annual_value")).state) == 0.0

    # thawing reopens the current periods
    await hass.services.async_call(
        "select", "select_option", {"entity_id": status, "option": "active"}, blocking=True
    )
    assert any(k.startswith(f"{CARD_ID}:") for k in entry.runtime_data.doc.instances)
    assert float(hass.states.get(owner_unused).state) > 0

    # persists across a reload
    await hass.services.async_call(
        "select", "select_option", {"entity_id": status, "option": "cancelled"}, blocking=True
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "cancelled"
