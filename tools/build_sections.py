#!/usr/bin/env python3
"""Rebuild the generated CardPerks overview sections.

Every list is driven by auto-entities matching on attributes, so a card added or
removed later needs no regeneration, and every icon takes its card's colour live.

Push each with tools/append_section.py, which replaces a section by its heading and
leaves the rest of a hand-edited view alone.

  python3 build_sections.py outdir/
"""

from __future__ import annotations

import json
import pathlib
import sys

from lovelace import (
    DAYS_UNTIL,
    attr,
    auto_cards,
    auto_rows,
    base_filter,
    gauge_grid,
    heading,
    note,
)

ACTIVE_ONLY = {"card_status": "active"}


def with_status(f: dict, **extra: str) -> dict:
    """Restrict a filter to active cards, plus any other attribute matches."""
    return {**f, "attributes": {**f.get("attributes", {}), **ACTIVE_ONLY, **extra}}


def dollars_left() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("Dollars left by benefit", "mdi:cash-clock"),
            note("Each arc is what is left of that credit, in its card's colour. Tap for detail."),
            gauge_grid(
                "benefit_remaining",
                name="s.attributes.benefit",
                maximum="(s.attributes.amount or (s.state | float(0)))",
                where="(s.state | float(0)) > 0",
                by_value=True,
            ),
        ],
    }


def checkoff() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("Check off", "mdi:cash-check"),
            note("Type the dollars you captured. Status follows from the amount."),
            auto_rows(
                [
                    {**with_status(base_filter(), status=s), "domain": "number"}
                    for s in ("unused", "partial")
                ],
                "Credits with money left",
                suffix="used",
            ),
        ],
    }


def by_card() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("By card", "mdi:credit-card-multiple"),
            note(
                "Share of each card's yearly credits captured over the trailing twelve "
                "months. Tap a gauge for the dollars behind it."
            ),
            gauge_grid("capture_rate"),
        ],
    }


def fees() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("Annual fees", "mdi:calendar-cash"),
            auto_cards(
                [with_status(base_filter(kind="fee_due"))],
                primary="{{ state_attr(entity, 'card') }}",
                secondary=(
                    "${{ " + attr("annual_fee") + " | round(0) | int }} · due "
                    "{{ states(entity) }} · " + DAYS_UNTIL + " days"
                ),
                icon="mdi:calendar-cash",
                sort={"method": "state", "numeric": False, "reverse": False},
            ),
        ],
    }


def expiring() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("Expiring within 30 days", "mdi:timer-sand"),
            auto_cards(
                [
                    with_status(base_filter(kind="benefit_expires"), status=s, days_left="< 31")
                    for s in ("unused", "partial")
                ],
                primary="{{ state_attr(entity, 'benefit') }}",
                secondary=(
                    "${{ " + attr("remaining") + " | round(0) | int }} left · "
                    "{{ state_attr(entity, 'card') }} · "
                    "{{ state_attr(entity, 'days_left') }} days"
                ),
                icon="mdi:timer-sand",
                sort={"method": "state", "numeric": False, "reverse": False},
            ),
        ],
    }


def coverage() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("Statement coverage", "mdi:file-document-check-outline"),
            note("A month with no statement is unknown, not proof a credit went unused."),
            auto_cards(
                [with_status(base_filter(kind="coverage_12m"))],
                primary="{{ state_attr(entity, 'card') }}",
                secondary=(
                    "{{ states(entity) }}/12 months · "
                    "{{ " + attr("statements_imported") + " }} files"
                    "{% set m = state_attr(entity, 'missing') or [] %}"
                    "{% if m %} · missing {{ m[:3] | join(', ') }}"
                    "{% if m | count > 3 %} +{{ m | count - 3 }}{% endif %}{% endif %}"
                ),
                icon="mdi:file-document-check-outline",
                sort={"method": "friendly_name"},
            ),
        ],
    }


def perk_values() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("What perks are worth to you", "mdi:tag-text-outline"),
            note("Lounge access and status carry no issuer amount, so the value is your call."),
            auto_rows(
                [{**with_status(base_filter(), kind="perk_value"), "domain": "number"}],
                "Perk values",
                suffix="value",
            ),
        ],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    outdir = pathlib.Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    sections = {
        "dollars_left": dollars_left(),
        "checkoff": checkoff(),
        "by_card": by_card(),
        "fees": fees(),
        "expiring": expiring(),
        "coverage": coverage(),
        "perk_values": perk_values(),
    }
    for name, section in sections.items():
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(section, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
