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
    DOLLARS,
    attr,
    auto_cards,
    base_filter,
    donut_by_card,
    gauge_grid,
    heading,
    note,
    peek_rows,
    wide_section,
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
            auto_cards(
                [{**with_status(base_filter(kind="benefit_remaining")), "state": "> 0"}],
                primary="{{ state_attr(entity, 'benefit') }}",
                secondary=DOLLARS + " left · {{ state_attr(entity, 'card') }}",
                icon="mdi:cash-clock",
            ),
        ],
    }


def checkoff() -> dict:
    return wide_section(
        [
            heading("Log a credit", "mdi:cash-check"),
            note("Type the dollars you captured. Status follows from the amount."),
            *peek_rows(
                [
                    {**with_status(base_filter(), status=s), "domain": "number"}
                    for s in ("unused", "partial")
                ],
                "Credits with money left",
                suffix="used",
            ),
        ]
    )


def by_card() -> dict:
    return {
        "type": "grid",
        "cards": [
            heading("By card", "mdi:credit-card-multiple"),
            note(
                "Trailing twelve months. Forfeited is money a period closed without you "
                "using it, which is gone rather than pending."
            ),
            auto_cards(
                [with_status(base_filter(kind="capture_rate"))],
                primary="{{ state_attr(entity, 'card') }}",
                secondary=(
                    "${{ " + attr("captured_12m") + " | round(0) | int }} of "
                    "${{ " + attr("annual_value") + " | round(0) | int }} captured · "
                    "${{ " + attr("forfeited_12m") + " | round(0) | int }} forfeited · "
                    "{{ states(entity) | float(0) | round(0) | int }}%"
                ),
                icon="mdi:cash-100",
                sort={"method": "friendly_name"},
            ),
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
    return wide_section(
        [
            heading("What perks are worth to you", "mdi:tag-text-outline"),
            note("Lounge access and status carry no issuer amount, so the value is your call."),
            *peek_rows(
                [{**with_status(base_filter(), kind="perk_value"), "domain": "number"}],
                "Perk values",
                suffix="value",
                noun="perks",
            ),
        ]
    )


def outstanding() -> dict:
    """The money left to use right now, as one ring sliced by card and benefit."""
    total = (
        "{% set vals = states.sensor | selectattr('attributes.kind', 'defined') "
        "| selectattr('attributes.kind', 'eq', 'unused_value') "
        "| selectattr('attributes.card_status', 'eq', 'active') "
        "| rejectattr('state', 'in', ['unknown', 'unavailable']) "
        "| map(attribute='state') | map('float', 0) | list %}"
        "{% set total = (vals | sum) or 1 %}"
    )
    return wide_section(
        [
            heading("Left to use, by card", "mdi:chart-donut"),
            note(
                "Each card is a slice, largest first; the shades within it are its "
                "individual credits."
            ),
            donut_by_card(),
            auto_cards(
                [{**with_status(base_filter(kind="unused_value")), "state": "> 0"}],
                primary="{{ state_attr(entity, 'card') }}",
                secondary=(
                    total + DOLLARS + " · {{ ((states(entity) | float(0)) / total * 100) "
                    "| round(0) | int }}% of the total"
                ),
                icon="mdi:circle-slice-8",
            ),
        ],
        halves=2,  # the ring on the left, its legend on the right
    )


def net_value() -> dict:
    """A gauge per card: captured over the trailing year, less the annual fee.

    The arc runs from paying the fee and getting nothing back, to capturing every
    credit the card offers. The annual value lives on the capture-rate sensor, so it
    is looked up by card id.
    """
    fee = "(s.attributes.annual_fee or 0)"
    annual = (
        "((states.sensor | selectattr('attributes.kind', 'defined') "
        "| selectattr('attributes.kind', 'eq', 'capture_rate') "
        "| selectattr('attributes.card_id', 'eq', s.attributes.card_id) "
        "| map(attribute='attributes.annual_value') | list | first) or 0)"
    )
    return {
        "type": "grid",
        "cards": [
            heading("Net value, by card", "mdi:scale-balance"),
            note(
                "Credits captured over the trailing twelve months, less the annual fee. "
                "Empty is paying the fee for nothing; full is capturing everything."
            ),
            gauge_grid(
                "net_value_12m",
                minimum=f"-{fee}",
                maximum=f"([{annual} - {fee}, 1 - {fee}] | max)",
                by_value=True,
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
        "outstanding": outstanding(),
        "net_value": net_value(),
    }
    for name, section in sections.items():
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(section, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
