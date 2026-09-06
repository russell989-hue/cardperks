#!/usr/bin/env python3
"""Generate one Lovelace subview per card, plus a navigation section for the overview.

Input is the card map produced on the HA box (device title -> card-level entity ids).
Output is a JSON list of views that tools/push_dashboard.py merges by path, so an
existing overview view is left alone.

  python3 build_card_views.py cards.json views.json [nav.yaml]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

SECTION_ICON = {
    "money": "mdi:cash-clock",
    "check": "mdi:check-circle-outline",
    "value": "mdi:tag-text-outline",
    "all": "mdi:format-list-bulleted",
}


def slugify(name: str) -> str:
    """Stable, URL-safe path for a card. The middot in titles has to go."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_name.lower())).strip("-")


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def auto_entities(
    title: str,
    device: str,
    *,
    pattern: str | None = None,
    domain: str | None = None,
    states: list[str] | None = None,
    state_filter: str | None = None,
    sort_method: str = "state",
    numeric: bool = True,
    reverse: bool = True,
    show_empty: bool = True,
) -> dict:
    base: dict = {"integration": "cardperks", "device": device}
    if pattern:
        base["entity_id"] = pattern
    if domain:
        base["domain"] = domain
    include = []
    if states:
        include.extend({**base, "state": s} for s in states)
    else:
        item = dict(base)
        if state_filter:
            item["state"] = state_filter
        include.append(item)
    return {
        "type": "custom:auto-entities",
        "card": {"type": "entities", "title": title, "state_color": True},
        "show_empty": show_empty,
        "filter": {
            "include": include,
            "exclude": [{"state": "unavailable"}, {"state": "unknown"}],
        },
        "sort": {"method": sort_method, "numeric": numeric, "reverse": reverse},
    }


def build_view(name: str, ids: dict[str, str]) -> dict:
    summary = {
        "type": "grid",
        "cards": [
            heading(name, "mdi:credit-card"),
            {
                "type": "tile",
                "entity": ids["unused_value"],
                "name": "Unused this period",
                "color": "green",
            },
            {"type": "tile", "entity": ids["net_value"], "name": "Net value, 12 months"},
            {"type": "tile", "entity": ids["fee_due"], "name": "Annual fee due"},
            {
                "type": "conditional",
                "conditions": [{"condition": "state", "entity": ids["fee_soon"], "state": "on"}],
                "card": {
                    "type": "tile",
                    "entity": ids["fee_soon"],
                    "name": "Fee due soon",
                    "color": "red",
                },
            },
        ],
    }
    return {
        "type": "sections",
        "title": name,
        "path": slugify(name),
        "icon": "mdi:credit-card",
        "subview": True,
        "max_columns": 3,
        "sections": [
            summary,
            {
                "type": "grid",
                "cards": [
                    heading("Money left", SECTION_ICON["money"]),
                    auto_entities(
                        "Credits with money left", name, pattern="*_remaining", state_filter="> 0"
                    ),
                ],
            },
            {
                "type": "grid",
                "cards": [
                    heading("Check off", SECTION_ICON["check"]),
                    auto_entities(
                        "Not yet used",
                        name,
                        domain="select",
                        states=["unused", "partial"],
                        sort_method="friendly_name",
                        numeric=False,
                        reverse=False,
                    ),
                ],
            },
            {
                "type": "grid",
                "cards": [
                    heading("What perks are worth to you", SECTION_ICON["value"]),
                    auto_entities(
                        "Perk values",
                        name,
                        domain="number",
                        sort_method="friendly_name",
                        numeric=False,
                        reverse=False,
                        show_empty=False,
                    ),
                ],
            },
            {
                "type": "grid",
                "cards": [
                    heading("Every benefit", SECTION_ICON["all"]),
                    auto_entities(
                        "Status",
                        name,
                        domain="select",
                        sort_method="friendly_name",
                        numeric=False,
                        reverse=False,
                    ),
                    auto_entities(
                        "Expiry dates",
                        name,
                        pattern="*_expires",
                        sort_method="state",
                        numeric=False,
                        reverse=False,
                    ),
                ],
            },
        ],
    }


def nav_section(cards: dict[str, dict], url_path: str) -> dict:
    """A section for the overview: one tap-through tile per card."""
    return {
        "type": "grid",
        "cards": [
            heading("Cards", "mdi:credit-card-multiple"),
            *[
                {
                    "type": "tile",
                    "entity": ids["unused_value"],
                    "name": name,
                    "icon": "mdi:credit-card",
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": f"/{url_path}/{slugify(name)}",
                    },
                }
                for name, ids in sorted(cards.items())
            ],
        ],
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        cards = json.load(fh)
    complete = {n: i for n, i in cards.items() if len(i) == 4}
    views = [build_view(n, i) for n, i in sorted(complete.items())]
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2)
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(nav_section(complete, "dashboard-cardperks"), fh, indent=2)
    print(f"{len(views)} subviews: {', '.join(v['path'] for v in views)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
