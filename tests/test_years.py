"""Per-cardmember-year history: what statements prove about each year of a card."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import DOMAIN
from custom_components.cardperks.models import HistoryRecord

from .conftest import CARD_ID


async def test_years_report_fee_captured_and_evidence(hass, setup_integration: MockConfigEntry):
    """Each cardmember year: fee seen, credits captured, net, and months a statement covers."""
    from homeassistant.helpers import entity_registry as er

    entry = setup_integration
    coord = entry.runtime_data
    doc = coord.doc

    # The card opened 2026-07-01, so years run July to June. Last year had a $450 fee line,
    # a $150 dining credit captured, and statements for nine of its months.
    doc.fees_seen[CARD_ID] = {"2025-07-02": 450.0, "2026-07-01": 450.0}
    doc.history.append(
        HistoryRecord(
            held_card_id=CARD_ID,
            benefit_id="dining_credit",
            period_start="2026-01-01",
            period_end="2026-06-30",
            final_status="used",
            amount=150.0,
            amount_used=150.0,
            closed_at="2026-07-01T00:05:00+00:00",
            closed_by="statement",
        )
    )
    doc.coverage[CARD_ID] = {f"2025-{m:02d}": "x" for m in (9, 10, 11, 12)} | {
        f"2026-{m:02d}": "x" for m in (1, 2, 3, 4, 5, 8)
    }
    coord.set_used(CARD_ID, "monthly_credit", 4)  # this year: $4 so far
    await hass.async_block_till_done()

    years = coord.data.card_summaries[CARD_ID].years
    assert [y.start.isoformat() for y in years] == ["2026-07-01", "2025-07-01"]

    this = years[0]
    assert this.current and this.fee == 450.0 and this.captured == 4.0 and this.net == -446.0
    assert (this.months, this.months_covered) == (3, 1)  # Jul, Aug, Sep so far; Aug covered

    last = years[1]
    assert not last.current and last.fee == 450.0 and last.captured == 150.0
    assert last.net == -300.0 and (last.months, last.months_covered) == (12, 9)

    # Two years back: nothing known, so not listed.
    assert all(y.start.year >= 2025 for y in years)

    eid = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{CARD_ID}_net_value_12m")
    rows = hass.states.get(eid).attributes["years"]
    assert rows[1]["net"] == -300.0 and rows[1]["months_covered"] == 9


async def test_import_keeps_every_fee_line(hass, setup_integration: MockConfigEntry, tmp_path):
    """A statement's fee lines are all kept by date, not only the newest."""
    from .test_statements import CHASE

    entry = setup_integration
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    path = tmp_path / "Chase1234_Activity.csv"
    path.write_text(CHASE, encoding="utf-8")
    await hass.services.async_call(
        DOMAIN, "import_statement", {"path": str(path)}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.doc.fees_seen[CARD_ID] == {"2026-07-01": 450.0}
