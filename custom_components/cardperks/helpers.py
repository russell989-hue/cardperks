"""Small helpers shared by setup, config flow, and services."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .catalog import PROGRAMS_DIR, SHIPPED_DIR, load_catalog
from .const import (
    CONF_ANNUAL_FEE,
    CONF_CLOSE_DATE,
    CONF_COLOR,
    CONF_ENABLED_CONDITIONAL,
    CONF_FEE_MONTH,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_NOT_APPLICABLE,
    CONF_NOTES,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PREVIOUS_LAST4,
    CONF_PRODUCT_ID,
    CONF_PROGRAM,
    CONF_PROGRAM_ID,
    CONF_ROLE,
    CONF_SOURCE,
    CONF_TIER,
    CONF_TIER_ID,
    CONF_VALID_THROUGH,
    DOMAIN,
    OVERRIDE_DIR,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
    SUBENTRY_STATUS,
    Role,
)
from .models import Catalog, CatalogProblem, HeldCard, LoyaltyStatus, Owner

DATA_CATALOG = "catalog"
DATA_PROBLEMS = "catalog_problems"


def override_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(OVERRIDE_DIR, "catalog"))


async def async_load_catalog(hass: HomeAssistant) -> tuple[Catalog, list[CatalogProblem]]:
    """Load (and cache) the catalog."""
    catalog, problems = await hass.async_add_executor_job(
        load_catalog, SHIPPED_DIR, override_dir(hass), PROGRAMS_DIR
    )
    hass.data.setdefault(DOMAIN, {})[DATA_CATALOG] = catalog
    hass.data[DOMAIN][DATA_PROBLEMS] = problems
    return catalog, problems


async def async_get_catalog(hass: HomeAssistant) -> Catalog:
    cached = hass.data.get(DOMAIN, {}).get(DATA_CATALOG)
    if cached is not None:
        return cached
    catalog, _ = await async_load_catalog(hass)
    return catalog


def today_local() -> date:
    return dt_util.now().date()


def now_iso() -> str:
    return dt_util.now().isoformat(timespec="seconds")


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def owner_from_subentry(sub: ConfigSubentry) -> Owner:
    return Owner(id=sub.subentry_id, name=sub.data.get(CONF_NAME) or sub.title)


def card_from_subentry(sub: ConfigSubentry) -> HeldCard:
    d = sub.data
    return HeldCard(
        id=sub.subentry_id,
        owner_id=d[CONF_OWNER_ID],
        product_id=d[CONF_PRODUCT_ID],
        role=Role(d.get(CONF_ROLE, Role.PRIMARY)),
        title=sub.title,
        parent_card_id=d.get(CONF_PARENT_CARD_ID) or None,
        open_date=_parse_date(d.get(CONF_OPEN_DATE)),
        fee_month=int(d[CONF_FEE_MONTH]) if d.get(CONF_FEE_MONTH) else None,
        last4=d.get(CONF_LAST4) or None,
        nickname=d.get(CONF_NICKNAME) or None,
        close_date=_parse_date(d.get(CONF_CLOSE_DATE)),
        notes=d.get(CONF_NOTES) or None,
        annual_fee=float(d[CONF_ANNUAL_FEE]) if d.get(CONF_ANNUAL_FEE) not in (None, "") else None,
        enabled_conditional=tuple(d.get(CONF_ENABLED_CONDITIONAL) or ()),
        previous_last4=tuple(d.get(CONF_PREVIOUS_LAST4) or ()),
        not_applicable=tuple(d.get(CONF_NOT_APPLICABLE) or ()),
        color=d.get(CONF_COLOR) or None,
    )


def status_from_subentry(sub: ConfigSubentry) -> LoyaltyStatus:
    d = sub.data
    return LoyaltyStatus(
        id=sub.subentry_id,
        owner_id=d[CONF_OWNER_ID],
        program=d[CONF_PROGRAM],
        tier=d[CONF_TIER],
        valid_through=_parse_date(d.get(CONF_VALID_THROUGH)),
        source=d.get(CONF_SOURCE) or "entered by hand",
        notes=d.get(CONF_NOTES) or None,
        program_id=d.get(CONF_PROGRAM_ID) or None,
        tier_id=d.get(CONF_TIER_ID) or None,
    )


def statuses_from_entry(entry: ConfigEntry) -> dict[str, LoyaltyStatus]:
    return {
        sub.subentry_id: status_from_subentry(sub)
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_STATUS
    }


def owners_from_entry(entry: ConfigEntry) -> dict[str, Owner]:
    return {
        sub.subentry_id: owner_from_subentry(sub)
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_OWNER
    }


def cards_from_entry(entry: ConfigEntry) -> dict[str, HeldCard]:
    return {
        sub.subentry_id: card_from_subentry(sub)
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_CARD
    }
