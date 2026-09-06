"""Repair issues: catalog staleness, bad override files, overdue statements."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, STALE_CATALOG_DAYS
from .coordinator import CardPerksCoordinator
from .helpers import today_local
from .models import Catalog, CatalogProblem


@callback
def async_check_catalog_issues(
    hass: HomeAssistant, catalog: Catalog, problems: list[CatalogProblem]
) -> None:
    today = today_local()
    stale_cutoff = today - timedelta(days=STALE_CATALOG_DAYS)

    for product in catalog.products.values():
        issue_id = f"stale_catalog_{product.id}"
        if product.last_verified < stale_cutoff:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="stale_catalog",
                translation_placeholders={
                    "product": f"{product.issuer_name} {product.name}",
                    "last_verified": product.last_verified.isoformat(),
                    "source_url": product.source_url,
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    unverified = sorted(
        f"{p.issuer_name} {p.name}" for p in catalog.products.values() if p.needs_verification
    )
    if unverified:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "catalog_needs_verification",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="catalog_needs_verification",
            translation_placeholders={"products": ", ".join(unverified)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "catalog_needs_verification")

    for problem in problems:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"invalid_override_{abs(hash(problem.path))}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="invalid_override",
            translation_placeholders={"path": problem.path, "error": problem.message},
        )


@callback
def async_check_statement_issues(hass: HomeAssistant, coordinator: CardPerksCoordinator) -> None:
    """One repair per card whose statement uploads have fallen behind.

    Runs on every snapshot, so importing the missing statement clears it at once.
    """
    for card_id, summary in coordinator.data.card_summaries.items():
        issue_id = f"statement_due_{card_id}"
        if summary.statement_due:
            card = coordinator.data.cards.get(card_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="statement_due",
                translation_placeholders={
                    "card": card.title if card else card_id,
                    "last_month": summary.last_statement_month or "",
                    "months": str(summary.statement_months_behind),
                },
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
