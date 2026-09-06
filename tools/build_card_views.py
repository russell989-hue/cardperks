#!/usr/bin/env python3
"""Generate one Lovelace subview per card, plus the Cards section for the overview.

Input is the live entity map from tools/cp_full.py on the HA box. Every icon takes
the card's colour live from the entity attribute, so changing the colour in the card
form needs no regeneration. Cancelled cards drop out of the overview by themselves.

Reading order is money first, then the things you do, then reference, then settings:

  At a glance      what is unused right now, and when the fee lands
  This year        a year's worth, captured, forfeited, capture rate
  Money on hand    credits with a balance, biggest first
  Record spending  the dollar boxes for anything not yet fully used
  Perk values      what lounge access and status are worth to you
  All benefits     every status and expiry date
  Card settings    status; colour is set in the card form

  python3 build_card_views.py cards.json views.json [nav.json]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

from lovelace import (
    DAYS_UNTIL,
    DOLLARS,
    attr,
    auto_cards,
    auto_rows,
    base_filter,
    coloured_row,
    heading,
    note,
    template_card,
)


def slugify(name: str) -> str:
    """Stable, URL-safe path for a card."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_name.lower())).strip("-")


def stat(entity: str, label: str, icon: str, value: str = DOLLARS) -> dict:
    return template_card(label, value, icon, entity=entity)


def build_view(card: dict) -> dict:
    name, card_id, ids, perks = card["title"], card["id"], card["ids"], card["perks"]
    scope = base_filter(card_id)

    at_a_glance = [heading(name, "mdi:credit-card")]
    if ids.get("unused_value"):
        at_a_glance.append(stat(ids["unused_value"], "Unused right now", "mdi:cash-clock"))
    if ids.get("fee_due"):
        at_a_glance.append(
            stat(
                ids["fee_due"],
                "Annual fee due",
                "mdi:calendar-cash",
                "${{ "
                + attr("annual_fee")
                + " | round(0) | int }} on {{ states(entity) }} · "
                + DAYS_UNTIL
                + " days",
            )
        )
    if ids.get("fee_soon"):
        at_a_glance.append(
            {
                "type": "conditional",
                "conditions": [{"condition": "state", "entity": ids["fee_soon"], "state": "on"}],
                "card": {
                    "type": "custom:mushroom-template-card",
                    "primary": "Fee due within 45 days",
                    "secondary": "Decide whether this card still earns its keep.",
                    "icon": "mdi:alert",
                    "icon_color": "red",
                    "entity": ids["fee_soon"],
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
    for key, label, icon, value in (
        ("annual_value", "A year's worth", "mdi:cash-100", DOLLARS),
        ("captured", "Captured", "mdi:cash-check", DOLLARS),
        ("forfeited", "Forfeited", "mdi:cash-remove", DOLLARS),
        ("capture_rate", "Capture rate", "mdi:percent-outline", "{{ states(entity) }}%"),
        ("net_value", "Net of the fee", "mdi:scale-balance", DOLLARS),
    ):
        if ids.get(key):
            this_year.append(stat(ids[key], label, icon, value))

    sections = [
        {"type": "grid", "cards": at_a_glance},
        {"type": "grid", "cards": this_year},
        {
            "type": "grid",
            "cards": [
                heading("Money on hand", "mdi:cash-clock"),
                auto_cards(
                    [{**base_filter(card_id, kind="benefit_remaining"), "state": "> 0"}],
                    primary="{{ state_attr(entity, 'benefit') }}",
                    secondary=DOLLARS + " left · expires {{ state_attr(entity, 'period_end') }}",
                    icon="mdi:cash-clock",
                ),
            ],
        },
        {
            "type": "grid",
            "cards": [
                heading("Record what you spent", "mdi:cash-check"),
                note("Type the dollars you captured. Status follows from the amount."),
                auto_rows(
                    [
                        {
                            **scope,
                            "domain": "number",
                            "attributes": {**scope["attributes"], "status": s},
                        }
                        for s in ("unused", "partial")
                    ],
                    "Not yet fully used",
                    suffix="used",
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
                        "entities": [coloured_row(p["entity"], p["benefit"]) for p in perks],
                    },
                ],
            }
        )

    sections.append(
        {
            "type": "grid",
            "cards": [
                heading("All benefits", "mdi:format-list-bulleted"),
                auto_cards(
                    [base_filter(card_id, kind="benefit_status")],
                    primary="{{ state_attr(entity, 'benefit') }}",
                    secondary=(
                        "{{ states(entity) | replace('_', ' ') | replace('n a', 'not applicable') }}"
                        "{% if state_attr(entity, 'amount') %} · "
                        "${{ " + attr("amount_used") + " | round(0) | int }} of "
                        "${{ " + attr("amount") + " | round(0) | int }}"
                        "{% elif state_attr(entity, 'amount_used') %} · "
                        "${{ " + attr("amount_used") + " | round(2) }} back{% endif %}"
                    ),
                    icon="mdi:gift-outline",
                    sort={"method": "friendly_name"},
                    show_empty=True,
                ),
            ],
        }
    )

    settings = [heading("Card settings", "mdi:credit-card-settings-outline")]
    if ids.get("status"):
        settings.append(
            note(
                "Frozen keeps the card and its history but stops tracking and drops it "
                "from every total. Cancelled also hides it from the overview."
            )
        )
        settings.append({"type": "entities", "entities": [coloured_row(ids["status"], "Status")]})
    settings.append(
        note(
            "Colour, open date, fee month, and benefits that do not apply are set under "
            "Settings > Devices & services > CardPerks > this card > Edit."
        )
    )
    sections.append({"type": "grid", "cards": settings})

    return {
        "type": "sections",
        "title": name,
        "path": slugify(name),
        "icon": "mdi:credit-card",
        "subview": True,
        "max_columns": 3,
        "sections": sections,
    }


def nav_section(cards: list[dict], url_path: str) -> dict:
    """One tap-through card per held card, in its own colour, hidden once cancelled."""
    tiles = []
    for c in cards:
        if not c["ids"].get("unused_value"):
            continue
        tile = template_card(
            c["title"],
            DOLLARS + " unused",
            "mdi:credit-card",
            entity=c["ids"]["unused_value"],
            tap={"action": "navigate", "navigation_path": f"/{url_path}/{slugify(c['title'])}"},
        )
        if c["ids"].get("status"):
            tile = {
                "type": "conditional",
                "conditions": [
                    {"condition": "state", "entity": c["ids"]["status"], "state_not": "cancelled"}
                ],
                "card": tile,
            }
        tiles.append(tile)
    return {"type": "grid", "cards": [heading("Cards", "mdi:credit-card-multiple"), *tiles]}


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = []
    for key, val in raw.items():
        ids = dict(val.get("card", {}))
        if val.get("status_entity"):
            ids["status"] = val["status_entity"]
        out.append({"id": key, "title": val["title"], "ids": ids, "perks": val.get("perks", [])})
    return sorted(out, key=lambda c: c["title"] or "")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cards = load(sys.argv[1])
    views = [build_view(c) for c in cards]
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2, ensure_ascii=False)
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(nav_section(cards, "dashboard-cardperks"), fh, indent=2, ensure_ascii=False)
    print(f"{len(views)} subviews")
    for c, v in zip(cards, views, strict=True):
        print(f"  {c['title']:45s} sections={len(v['sections'])} ids={len(c['ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
