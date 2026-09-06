"""Small helpers shared by setup, config flow, and services."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .catalog import SHIPPED_DIR, load_catalog
from .const import (
    CONF_ANNUAL_FEE,
    CONF_CLOSE_DATE,
    CONF_ENABLED_CONDITIONAL,
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
    OVERRIDE_DIR,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
    Role,
)
from .models import Catalog, CatalogProblem, HeldCard, Owner

DATA_CATALOG = "catalog"
DATA_PROBLEMS = "catalog_problems"


def override_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(OVERRIDE_DIR, "catalog"))


async def async_load_catalog(hass: HomeAssistant) -> tuple[Catalog, list[CatalogProblem]]:
    """Load (and cache) the catalog."""
    catalog, problems = await hass.async_add_executor_job(
        load_catalog, SHIPPED_DIR, override_dir(hass)
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
    )


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
