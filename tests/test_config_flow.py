"""Config flow and subentry flow tests."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.const import (
    CONF_FEE_MONTH,
    CONF_FIRST_OWNER,
    CONF_HOUSEHOLD_NAME,
    CONF_ISSUER,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PRODUCT_ID,
    CONF_ROLE,
    DOMAIN,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
)

from .conftest import AU_CARD_ID, CARD_ID, OWNER_ID


async def test_user_flow_creates_entry_with_first_owner(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.cardperks.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOUSEHOLD_NAME: "Russell House", CONF_FIRST_OWNER: "Brian"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Russell House"
    entry = result["result"]
    owners = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_OWNER]
    assert len(owners) == 1 and owners[0].title == "Brian" and owners[0].unique_id == "brian"


async def test_second_instance_aborts(hass, mock_entry: MockConfigEntry):
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_add_owner_subentry(hass, setup_integration: MockConfigEntry):
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_OWNER), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Sam"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    owners = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_OWNER]
    assert {o.title for o in owners} == {"Brian", "Nick", "Sam"}

    # duplicate name aborts
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_OWNER), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "brian"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_add_primary_card_subentry(hass, setup_integration: MockConfigEntry):
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CARD), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_OWNER_ID: OWNER_ID, CONF_ISSUER: "testbank", CONF_ROLE: "primary"}
    )
    assert result["step_id"] == "product"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_PRODUCT_ID: "test_basic"}
    )
    assert result["step_id"] == "details"

    # missing anniversary info
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LAST4: "9999"}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {
        "base": "need_anniversary"
    }

    # bad last4
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_FEE_MONTH: "11", CONF_LAST4: "12a4"}
    )
    assert result["errors"] == {CONF_LAST4: "invalid_last4"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_FEE_MONTH: "11", CONF_LAST4: "9999"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Basic Card (Brian ·9999)"
    await hass.async_block_till_done()
    sub = next(s for s in entry.subentries.values() if s.data.get(CONF_LAST4) == "9999")
    assert sub.data[CONF_FEE_MONTH] == 11 and sub.data[CONF_OPEN_DATE] is None
    assert sub.data[CONF_PRODUCT_ID] == "test_basic" and sub.data[CONF_ROLE] == "primary"


async def test_add_au_card_requires_parent(hass, setup_integration: MockConfigEntry):
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CARD), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_OWNER_ID: "owner_nick", CONF_ISSUER: "testbank", CONF_ROLE: "authorized_user"},
    )
    assert result["step_id"] == "product"
    # picking a product with no matching primary card fails
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_PRODUCT_ID: "test_basic", CONF_PARENT_CARD_ID: CARD_ID}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "no_parent_card"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_PRODUCT_ID: "test_premium", CONF_PARENT_CARD_ID: CARD_ID}
    )
    assert result["step_id"] == "details"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NICKNAME: "Nick's AU"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "Nick's AU"
    await hass.async_block_till_done()
    sub = next(s for s in entry.subentries.values() if s.title == "Nick's AU")
    # inherited from parent
    assert sub.data[CONF_OPEN_DATE] == "2026-07-01"
    assert sub.data[CONF_PARENT_CARD_ID] == CARD_ID


async def test_reconfigure_card(hass, setup_integration: MockConfigEntry):
    entry = setup_integration
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CARD),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": CARD_ID},
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"
    with patch("custom_components.cardperks.async_setup_entry", return_value=True) as setup:
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_OPEN_DATE: "2024-06-01", CONF_LAST4: "1234", CONF_NICKNAME: "Big Blue"},
        )
        assert (
            result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
        )
        await hass.async_block_till_done()
    sub = entry.subentries[CARD_ID]
    assert sub.title == "Big Blue" and sub.data[CONF_OPEN_DATE] == "2024-06-01"
    assert sub.data[CONF_PRODUCT_ID] == "test_premium"  # immutable
    assert setup.called  # update listener reloaded the entry


async def test_remove_card_subentry_cleans_up_entities(hass, setup_integration: MockConfigEntry):
    from homeassistant.helpers import entity_registry as er

    entry = setup_integration
    registry = er.async_get(hass)
    before = [e for e in registry.entities.values() if e.config_subentry_id == AU_CARD_ID]
    assert before
    assert hass.config_entries.async_remove_subentry(entry, AU_CARD_ID)
    await hass.async_block_till_done()
    after = [e for e in registry.entities.values() if e.config_subentry_id == AU_CARD_ID]
    assert after == []
