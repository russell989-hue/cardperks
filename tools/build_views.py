#!/usr/bin/env python3
"""Build the three top-level views of the CardPerks dashboard.

  Overview   the household at a glance, the cards, the big credits closing soon,
             everything expiring this month, and the ring of dollars left
  Money      where the year's dollars went, net value, fees, the big-ticket ring
  Upkeep     statements (overdue and coverage), logging a credit, perk values

Every list and tile is a template over entity attributes, so a card added later
appears by itself, including its tile on the Overview. Card subviews come from
build_card_views.py; sections shared with them come from build_sections.py.

  python3 build_views.py views_main.json
"""

from __future__ import annotations

import json
import sys

from build_sections import (
    BIG_TICKET_DAYS,
    BIG_TICKET_MIN,
    big_ticket_list,
    by_card,
    checkoff,
    coverage,
    expiring,
    fees,
    net_value,
    outstanding,
    perk_values,
    where_big_dollars_went,
)
from lovelace import ONLY_ACTIVE, _template_cards, auto_cards, full_width, heading, note

THEME = "CardPerks"
DASHBOARD = "dashboard-cardperks"


def span(section: dict, n: int) -> dict:
    return {**section, "column_span": n}


# ------------------------------------------------------------------ household figures


def _owner_sum(kind: str) -> str:
    """Jinja that leaves the household total of an owner rollup in `ns.v`."""
    return (
        "{% set ns = namespace(v=0.0) %}"
        f"{{% for s in states.sensor if s.attributes.get('kind') == '{kind}' "
        "and s.attributes.get('owner') is not none "
        "and s.state not in ['unknown', 'unavailable'] %}"
        "{% set ns.v = ns.v + (s.state | float(0)) %}{% endfor %}"
    )


def _stat(primary: str, secondary: str, icon: str, color: str, tap: dict | None = None) -> dict:
    card = {
        "type": "custom:mushroom-template-card",
        "primary": primary,
        "secondary": secondary,
        "icon": icon,
        "icon_color": color,
        "multiline_secondary": True,
        "grid_options": {"columns": 12},
    }
    if tap:
        card["tap_action"] = tap
    return card


def at_a_glance() -> dict:
    """Four figures that answer the question the dashboard exists for."""
    left = _owner_sum("unused_credits") + "${{ ns.v | round(0) | int }} left to use"
    left_sub = (
        "{% set ns = namespace(w=0, m=0) %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'benefit_expires' "
        f"and {ONLY_ACTIVE} and s.attributes.get('status') in ['unused', 'partial'] "
        "and (s.attributes.get('remaining') or 0) > 0 "
        "and s.attributes.get('days_left') is not none %}"
        "{% if s.attributes.get('days_left') <= 7 %}{% set ns.w = ns.w + 1 %}{% endif %}"
        "{% if s.attributes.get('days_left') <= 30 %}{% set ns.m = ns.m + 1 %}{% endif %}"
        "{% endfor %}"
        "{{ ns.w }} closing this week · {{ ns.m }} within 30 days"
    )
    captured = _owner_sum("captured_12m") + "${{ ns.v | round(0) | int }} captured this year"
    captured_sub = (
        _owner_sum("captured_12m")
        + "{% set cap = ns.v %}"
        + _owner_sum("annual_value")
        .replace("ns = namespace", "na = namespace")
        .replace("ns.v", "na.v")
        + "{{ ((cap / na.v * 100) if na.v else 0) | round(0) | int }}% of ${{ na.v | round(0) | int }} on offer"
    )
    missed = _owner_sum("forfeited_12m") + "${{ ns.v | round(0) | int }} missed this year"
    missed_sub = (
        "{% set ns = namespace(unk=0.0) %}"
        f"{{% for s in states.sensor if s.attributes.get('kind') == 'capture_rate' and {ONLY_ACTIVE} %}}"
        "{% set ns.unk = ns.unk + (s.attributes.get('unknown_12m') or 0) %}{% endfor %}"
        "${{ ns.unk | round(0) | int }} more unknown: months with no statement"
    )
    soon = (
        "{% set ns = namespace(best=none) %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'benefit_expires' "
        f"and {ONLY_ACTIVE} and s.attributes.get('status') in ['unused', 'partial'] "
        f"and (s.attributes.get('remaining') or 0) >= {BIG_TICKET_MIN} "
        "and s.state not in ['unknown', 'unavailable'] %}"
        "{% if ns.best is none or (s.attributes.get('days_left') or 9999) "
        "< (ns.best.attributes.get('days_left') or 9999) %}{% set ns.best = s %}{% endif %}"
        "{% endfor %}"
    )
    soon_primary = soon + (
        "{% if ns.best %}${{ (ns.best.attributes.get('remaining') or 0) | round(0) | int }} · "
        "{{ ns.best.attributes.get('benefit') }}{% else %}Nothing big closing soon{% endif %}"
    )
    soon_secondary = soon + (
        "{% if ns.best %}{{ ns.best.attributes.get('card') }} · closes in "
        "{{ ns.best.attributes.get('days_left') }} days{% else %}"
        f"No credit of ${BIG_TICKET_MIN} or more closes within {BIG_TICKET_DAYS} days{{% endif %}}"
    )
    return span(
        {
            "type": "grid",
            "cards": [
                heading("At a glance", "mdi:view-dashboard-outline"),
                _stat(left, left_sub, "mdi:cash-clock", "amber"),
                _stat(captured, captured_sub, "mdi:cash-check", "green"),
                _stat(missed, missed_sub, "mdi:cash-remove", "red"),
                _stat(
                    soon_primary,
                    soon_secondary,
                    "mdi:star-circle-outline",
                    "blue",
                    tap={"action": "navigate", "navigation_path": f"/{DASHBOARD}/money"},
                ),
            ],
        },
        2,
    )


# ------------------------------------------------------------------ the cards


def card_tiles() -> dict:
    """One tile per active card, in its colour, from a template: a new card appears by
    itself. Tapping opens the card's own view; the path is the title slugified the way
    build_card_views.py does it."""
    template = (
        "{% set ns = namespace(cards=[]) %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'unused_value' "
        f"and {ONLY_ACTIVE} and s.state not in ['unknown', 'unavailable'] %}}"
        "{% set rate = states.sensor | selectattr('attributes.kind', 'defined') "
        "| selectattr('attributes.kind', 'eq', 'capture_rate') "
        "| selectattr('attributes.card_id', 'eq', s.attributes.get('card_id')) "
        "| map(attribute='state') | list | first %}"
        "{% set path = '/"
        + DASHBOARD
        + "/' ~ (s.attributes.get('card') | slugify | replace('_', '-')) %}"
        "{% set ns.cards = ns.cards + [{'type': 'custom:mushroom-template-card', "
        "'entity': s.entity_id, 'primary': s.attributes.get('card'), "
        "'secondary': '$' ~ (s.state | float(0) | round(0) | int) ~ ' left · ' "
        "~ ((rate | float(0)) | round(0) | int) ~ '% captured', "
        "'icon': 'mdi:credit-card', 'icon_color': s.attributes.get('color') or 'grey', "
        "'multiline_secondary': true, "
        "'tap_action': {'action': 'navigate', 'navigation_path': path}, "
        "'sort': s.attributes.get('card')}] %}"
        "{% endfor %}"
        "{{ ns.cards | sort(attribute='sort') }}"
    )
    return span(
        {
            "type": "grid",
            "cards": [
                heading("Cards", "mdi:credit-card-multiple"),
                note("Tap a card for its own page. Frozen and cancelled cards are not shown."),
                full_width(_template_cards(template, columns=2)),
            ],
        },
        2,
    )


# ------------------------------------------------------------------ upkeep


def statements() -> dict:
    """Overdue uploads first, then how much of the year each card's statements cover."""
    overdue = auto_cards(
        [
            {
                "domain": "binary_sensor",
                "attributes": {"kind": "statement_due", "card_status": "active"},
                "state": "on",
            }
        ],
        primary="{{ state_attr(entity, 'card') }}",
        secondary=(
            "Newest statement covers {{ state_attr(entity, 'last_statement_month') }} · "
            "{{ state_attr(entity, 'months_behind') }} months behind"
        ),
        icon="mdi:file-document-alert-outline",
        sort={
            "method": "attribute",
            "attribute": "months_behind",
            "numeric": True,
            "reverse": True,
        },
    )
    cov = coverage()
    return span(
        {
            "type": "grid",
            "cards": [
                heading("Statements", "mdi:file-document-check-outline"),
                note(
                    "Drop an export in config/cardperks/statements/ and it is imported by itself. "
                    "A month with no statement is unknown, not proof a credit went unused."
                ),
                overdue,
                *cov["cards"][2:],  # the coverage list, without its own heading and note
            ],
        },
        1,
    )


# ------------------------------------------------------------------ views


def overview() -> dict:
    return {
        "type": "sections",
        "title": "My Cards Dashboard",
        "path": "cardperks",
        "icon": "mdi:credit-card-multiple",
        "theme": THEME,
        "max_columns": 4,
        "show_icon_and_title": True,
        "badges": [
            {
                "type": "shortcut",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": "/config/integrations/integration/cardperks",
                },
                "text": "Settings",
                "icon": "mdi:cog-outline",
                "color": "grey",
            }
        ],
        "sections": [
            at_a_glance(),
            card_tiles(),
            span(big_ticket_list(), 1),
            span(expiring(), 1),
            span(outstanding(), 2),
        ],
    }


def money() -> dict:
    return {
        "type": "sections",
        "title": "Money",
        "path": "money",
        "icon": "mdi:cash-multiple",
        "theme": THEME,
        "max_columns": 4,
        "show_icon_and_title": True,
        "sections": [
            span(by_card(), 2),
            span(net_value(), 1),
            span(fees(), 1),
            span(where_big_dollars_went(), 2),
        ],
    }


def upkeep() -> dict:
    return {
        "type": "sections",
        "title": "Upkeep",
        "path": "upkeep",
        "icon": "mdi:clipboard-check-outline",
        "theme": THEME,
        "max_columns": 4,
        "show_icon_and_title": True,
        "sections": [
            statements(),
            span(checkoff(), 2),
            span(perk_values(), 2),
        ],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    views = [overview(), money(), upkeep()]
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2, ensure_ascii=False)
    for v in views:
        print(f"  {v['path']:10} {len(v['sections'])} sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
