#!/usr/bin/env python3
"""Generate one Lovelace subview per card, plus a navigation section for the overview.

Input is the live entity map from tools/cp_full.py on the HA box, so nothing is
hardcoded and the layout follows whatever benefits a card actually has.

Reading order is money first, then the things you do, then reference, then settings:

  At a glance      what is unused right now, and when the fee lands
  This year        a year's worth, captured, forfeited, capture rate
  Money on hand    credits with a balance, biggest first
  Record spending  the dollar boxes for anything not yet fully used
  Perk values      what lounge access and status are worth to you
  All benefits     every status and expiry date, including used and n/a
  Card settings    the colour this card wears everywhere

  python3 build_card_views.py cards.json views.json [nav.json]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

CARD_TILES = (
    ("unused_value", "Unused right now"),
    ("fee_due", "Annual fee due"),
)

YEAR_TILES = (
    ("annual_value", "A year's worth"),
    ("captured", "Captured"),
    ("forfeited", "Forfeited"),
    ("capture_rate", "Capture rate"),
    ("net_value", "Net of the fee"),
)


def slugify(name: str) -> str:
    """Stable, URL-safe path for a card. The middot in titles has to go."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_name.lower())).strip("-")


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def note(text: str) -> dict:
    return {"type": "markdown", "text_only": True, "content": text}


def auto_entities(
    title: str,
    device: str,
    *,
    pattern: str | None = None,
    domain: str | None = None,
    attributes: list[dict] | None = None,
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
    if attributes:
        include = [{**base, "attributes": a} for a in attributes]
    else:
        item = dict(base)
        if state_filter:
            item["state"] = state_filter
        include = [item]
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


def build_view(name: str, ids: dict, color: str | None, perks: list[dict]) -> dict:
    tint = color or "grey"

    at_a_glance = [heading(name, "mdi:credit-card")]
    at_a_glance += [
        {"type": "tile", "entity": ids[key], "name": label, "color": tint}
        for key, label in CARD_TILES
        if ids.get(key)
    ]
    if ids.get("fee_soon"):
        at_a_glance.append(
            {
                "type": "conditional",
                "conditions": [{"condition": "state", "entity": ids["fee_soon"], "state": "on"}],
                "card": {
                    "type": "tile",
                    "entity": ids["fee_soon"],
                    "name": "Fee due soon",
                    "color": "red",
                },
            }
        )

    this_year = [
        heading("This year", "mdi:cash-100"),
        note(
            "Trailing twelve months. Forfeited is money a period closed without you "
            "using it, which is gone rather than pending."
        ),
    ]
    this_year += [
        {"type": "tile", "entity": ids[key], "name": label, "color": tint}
        for key, label in YEAR_TILES
        if ids.get(key)
    ]

    sections = [
        {"type": "grid", "cards": at_a_glance},
        {"type": "grid", "cards": this_year},
        {
            "type": "grid",
            "cards": [
                heading("Money on hand", "mdi:cash-clock"),
                auto_entities(
                    "Credits with a balance", name, pattern="*_remaining", state_filter="> 0"
                ),
            ],
        },
        {
            "type": "grid",
            "cards": [
                heading("Record what you spent", "mdi:cash-check"),
                note("Type the dollars you captured. The status follows from the amount."),
                auto_entities(
                    "Not yet fully used",
                    name,
                    domain="number",
                    attributes=[{"status": "unused"}, {"status": "partial"}],
                    sort_method="friendly_name",
                    numeric=False,
                    reverse=False,
                    show_empty=False,
                ),
            ],
        },
    ]

    if perks:
        sections.append(
            {
                "type": "grid",
                "cards": [
                    heading("What perks are worth to you", "mdi:tag-text-outline"),
                    note("These carry no issuer amount, so the value is your call."),
                    {
                        "type": "entities",
                        "entities": [{"entity": p["entity"], "name": p["benefit"]} for p in perks],
                    },
                ],
            }
        )

    sections.append(
        {
            "type": "grid",
            "cards": [
                heading("All benefits", "mdi:format-list-bulleted"),
                auto_entities(
                    "Status",
                    name,
                    pattern="*_status",
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
        }
    )

    if ids.get("color"):
        sections.append(colour_section(ids["color"]))

    return {
        "type": "sections",
        "title": name,
        "path": slugify(name),
        "icon": "mdi:credit-card",
        "subview": True,
        "max_columns": 3,
        "sections": sections,
    }


def colour_section(entity: str) -> dict:
    """Compact: a dropdown plus a swatch of the current colour.

    A grid of nineteen swatches was clearer but ate a screen for something set once,
    so the select stays a dropdown and the dot shows what is currently chosen.
    """
    current = (
        "{% set c = states('" + entity + "') %}"
        '<span style="color: var(--{{ c }}-color); font-size: 1.4em">&#9679;</span> '
        "&nbsp;**{{ c | replace('-', ' ') }}** &mdash; identifies this card on every dashboard."
    )
    return {
        "type": "grid",
        "cards": [
            heading("Card colour", "mdi:palette"),
            {"type": "markdown", "content": current},
            {"type": "entities", "entities": [{"entity": entity, "name": "Colour"}]},
        ],
    }


def nav_section(cards: list[dict], url_path: str) -> dict:
    """A section for the overview: one tap-through tile per card, in its own colour."""
    return {
        "type": "grid",
        "cards": [
            heading("Cards", "mdi:credit-card-multiple"),
            *[
                {
                    "type": "tile",
                    "entity": c["ids"]["unused_value"],
                    "name": c["title"],
                    "icon": "mdi:credit-card",
                    "color": c["color"] or "grey",
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": f"/{url_path}/{slugify(c['title'])}",
                    },
                }
                for c in cards
                if c["ids"].get("unused_value")
            ],
        ],
    }


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = []
    for val in raw.values():
        ids = dict(val.get("card", {}))
        if val.get("color_entity"):
            ids["color"] = val["color_entity"]
        out.append(
            {
                "title": val["title"],
                "color": val.get("color"),
                "ids": ids,
                "perks": val.get("perks", []),
            }
        )
    return sorted(out, key=lambda c: c["title"] or "")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cards = load(sys.argv[1])
    views = [build_view(c["title"], c["ids"], c["color"], c["perks"]) for c in cards]
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2)
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(nav_section(cards, "dashboard-cardperks"), fh, indent=2)
    print(f"{len(views)} subviews")
    for c, v in zip(cards, views, strict=True):
        print(
            f"  {c['title']:45s} {c['color'] or '-':12s} "
            f"sections={len(v['sections'])} perks={len(c['perks'])} ids={len(c['ids'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
