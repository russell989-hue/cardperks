#!/usr/bin/env python3
"""Generate the CardPerks Lovelace view (sections layout).

Writes JSON to stdout or a file. Push it with tools/push_dashboard.py, which runs
on the HA box and saves via the same websocket command the UI editor uses.

Custom cards used (all already installed via HACS on this instance):
  custom:auto-entities  - lists entities by integration, so the view needs no
                          hardcoded entity ids and stays correct as cards change.
"""

from __future__ import annotations

import json
import sys

OWNERS = ["brian", "nick"]

EXPIRING_TABLE = """\
{%- set ns = namespace(rows=[]) -%}
{%- for s in [OWNER_SENSORS] -%}
  {%- for i in state_attr(s, 'items') or [] -%}
    {%- set ns.rows = ns.rows + [i] -%}
  {%- endfor -%}
{%- endfor -%}
{%- set rows = ns.rows | sort(attribute='expires') -%}
{%- if rows | count == 0 -%}
Nothing expires in the next 30 days.
{%- else -%}
| Benefit | Card | Left | Days |
|---|---|--:|--:|
{% for r in rows -%}
| {{ r.benefit }} | {{ r.card }} | ${{ r.remaining | round(0) | int }} | \
{{ (((r.expires | as_timestamp) - (now() | as_timestamp)) / 86400) | round(0) | int }} |
{% endfor -%}
{%- endif -%}
"""

HEADER = """\
{%- set b = states('sensor.brian_unused_credits') | float(0) -%}
{%- set n = states('sensor.nick_unused_credits') | float(0) -%}
{%- set wk = states('sensor.brian_expiring_within_7_days') | int(0)
           + states('sensor.nick_expiring_within_7_days') | int(0) -%}
{%- set mo = states('sensor.brian_expiring_within_30_days') | int(0)
           + states('sensor.nick_expiring_within_30_days') | int(0) -%}
## ${{ (b + n) | round(0) | int }} unused

**{{ wk }}** expiring within 7 days &nbsp;&nbsp;·&nbsp;&nbsp; **{{ mo }}** within 30 days

Brian ${{ b | round(0) | int }} &nbsp;&nbsp;·&nbsp;&nbsp; Nick ${{ n | round(0) | int }}
"""


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def auto_entities(
    title: str,
    pattern: str | None = None,
    *,
    domain: str | None = None,
    states: list[str] | None = None,
    state_filter: str | None = None,
    sort_method: str = "state",
    numeric: bool = True,
    reverse: bool = True,
    show_empty: bool = False,
    card_type: str = "entities",
) -> dict:
    """auto-entities card scoped to the cardperks integration."""
    base: dict = {"integration": "cardperks"}
    if pattern:
        base["entity_id"] = pattern
    if domain:
        base["domain"] = domain
    include = []
    if states:
        for s in states:
            include.append({**base, "state": s})
    else:
        item = dict(base)
        if state_filter:
            item["state"] = state_filter
        include.append(item)
    return {
        "type": "custom:auto-entities",
        "card": {"type": card_type, "title": title, "state_color": True},
        "show_empty": show_empty,
        "filter": {
            "include": include,
            "exclude": [{"state": "unavailable"}, {"state": "unknown"}],
        },
        "sort": {"method": sort_method, "numeric": numeric, "reverse": reverse},
    }


def build_view() -> dict:
    owner_sensors = ", ".join(f"'sensor.{o}_expiring_within_30_days'" for o in OWNERS)

    overview = {
        "type": "grid",
        "cards": [
            heading("Money at risk", "mdi:cash-clock"),
            {"type": "markdown", "content": HEADER, "text_only": True},
            *[
                {
                    "type": "tile",
                    "entity": f"sensor.{o}_unused_credits",
                    "name": f"{o.title()} unused",
                    "icon": "mdi:cash-multiple",
                    "color": "green",
                }
                for o in OWNERS
            ],
            *[
                {
                    "type": "tile",
                    "entity": f"sensor.{o}_expiring_within_7_days",
                    "name": f"{o.title()} expiring this week",
                    "color": "red",
                }
                for o in OWNERS
            ],
        ],
    }

    expiring = {
        "type": "grid",
        "cards": [
            heading("Expiring within 30 days", "mdi:timer-sand"),
            {
                "type": "markdown",
                "content": EXPIRING_TABLE.replace("OWNER_SENSORS", owner_sensors),
            },
        ],
    }

    dollars = {
        "type": "grid",
        "cards": [
            heading("Dollars left by benefit", "mdi:cash-clock"),
            auto_entities("Credits with money left", "*_remaining", state_filter="> 0"),
        ],
    }

    checkoff = {
        "type": "grid",
        "cards": [
            heading("Check off", "mdi:check-circle-outline"),
            auto_entities(
                "Not yet used",
                domain="select",
                states=["unused", "partial"],
                sort_method="friendly_name",
                numeric=False,
                reverse=False,
            ),
        ],
    }

    by_card = {
        "type": "grid",
        "cards": [
            heading("By card", "mdi:credit-card-multiple"),
            auto_entities("Unused value", "*_unused_value", state_filter="> 0"),
            auto_entities(
                "Net value, trailing 12 months",
                "*_net_value_12_months",
                sort_method="state",
                reverse=False,
            ),
        ],
    }

    fees = {
        "type": "grid",
        "cards": [
            heading("Annual fees", "mdi:calendar-cash"),
            auto_entities(
                "Next fee dates",
                "*_annual_fee_due",
                sort_method="state",
                numeric=False,
                reverse=False,
            ),
            auto_entities(
                "Fee within 45 days",
                domain="binary_sensor",
                states=["on"],
                sort_method="friendly_name",
                numeric=False,
                reverse=False,
                show_empty=False,
            ),
        ],
    }

    signup = {
        "type": "grid",
        "cards": [
            heading("Sign-up bonuses & 5/24", "mdi:trophy-outline"),
            *[
                {
                    "type": "tile",
                    "entity": f"sensor.{o}_5_24_count",
                    "name": f"{o.title()} 5/24",
                    "icon": "mdi:counter",
                }
                for o in OWNERS
            ],
            auto_entities(
                "Sign-up bonus status",
                "*_sign_up_bonus",
                domain="select",
                sort_method="friendly_name",
                numeric=False,
                reverse=False,
            ),
        ],
    }

    return {
        "type": "sections",
        "title": "CardPerks",
        "path": "cardperks",
        "icon": "mdi:credit-card-multiple",
        "max_columns": 3,
        "sections": [overview, expiring, dollars, checkoff, by_card, fees, signup],
    }


if __name__ == "__main__":
    out = json.dumps(build_view(), indent=2)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        print(out)
