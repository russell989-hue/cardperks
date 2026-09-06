#!/usr/bin/env python3
"""Generate one Lovelace subview per card, plus the Cards section for the overview.

Input is the live entity map from tools/cp_full.py on the HA box. Every graph, list
and icon takes the card's colour live from the entity attribute, so changing the
colour in the card form needs no regeneration. Cancelled cards drop out of the
overview by themselves.

Reading order is money first, then the things you do, then reference, then settings:

  Ring             this card's credits left to use, beside the money-on-hand list
  This year        a stacked bar of where the year's dollars went, then gauges for
                   capture rate, net value and statement coverage, then the fee
  Log a credit     the dollar boxes for anything not yet fully used, three peeking
  Perk values      what lounge access and status are worth to you
  All benefits     every status, folded
  Card settings    status; colour is set in the card form; folded

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
    NET_MAX,
    NET_MIN,
    ONLY_CARD,
    attr,
    auto_cards,
    base_filter,
    coloured_row,
    donut_by_card,
    expander,
    gauge_grid,
    half,
    heading,
    money_bars,
    note,
    peek_rows,
    perk_rows_for_card,
    template_card,
    third,
    wide_section,
)

THEME = "CardPerks"  # themes/cardperks.yaml; applied per view so the rest of HA keeps its own


def slugify(name: str) -> str:
    """Stable, URL-safe path for a card."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_name.lower())).strip("-")


def gauge(card_id: str, kind: str, label: str, **kw: str) -> dict:
    """One gauge for one card, coloured live, a third of a wide section."""
    return third(
        gauge_grid(
            kind, name=f"'{label}'", where=ONLY_CARD.format(card_id=card_id), columns=1, **kw
        )
    )


def build_view(card: dict) -> dict:
    name, card_id, ids = card["title"], card["id"], card["ids"]
    scope = base_filter(card_id)

    ring = wide_section(
        [
            heading(name, "mdi:credit-card"),
            half(donut_by_card(220, card_id=card_id)),
            half(
                auto_cards(
                    [{**base_filter(card_id, kind="benefit_remaining"), "state": "> 0"}],
                    primary="{{ state_attr(entity, 'benefit') }}",
                    secondary=DOLLARS + " left · until {{ state_attr(entity, 'period_end') }}",
                    icon="mdi:cash-clock",
                )
            ),
        ]
    )

    year = [
        heading("This year", "mdi:cash-100"),
        note(
            "Trailing twelve months. Green is captured, red forfeited, grey unknown "
            "(months with no statement); the dim remainder is still open to capture."
        ),
        money_bars(card_id=card_id, with_name=False),
        gauge(card_id, "capture_rate", "Capture rate"),
        gauge(card_id, "net_value_12m", "Net of the fee", minimum=NET_MIN, maximum=NET_MAX),
        gauge(card_id, "coverage_12m", "Months with a statement", maximum="12"),
    ]
    if ids.get("fee_due"):
        year.append(
            template_card(
                "Annual fee",
                "${{ "
                + attr("annual_fee")
                + " | round(0) | int }} due {{ states(entity) }} · "
                + DAYS_UNTIL
                + " days",
                "mdi:calendar-cash",
                entity=ids["fee_due"],
            )
        )
    if ids.get("fee_soon"):
        year.append(
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

    log = wide_section(
        [
            heading("Log a credit", "mdi:cash-check"),
            note("Type the dollars you captured. Status follows from the amount."),
            *peek_rows(
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
        ]
    )

    sections = [ring, wide_section(year), log]

    sections.append(
        {
            "type": "grid",
            "cards": [
                heading("What perks are worth to you", "mdi:tag-text-outline"),
                note(
                    "These carry no issuer amount, so the value is your call. A perk shared "
                    "with other cards is one number for all of them; this card's share is shown."
                ),
                perk_rows_for_card(card_id),
            ],
        }
    )

    sections.append(
        wide_section(
            [
                expander(
                    heading("All benefits", "mdi:format-list-bulleted"),
                    [
                        auto_cards(
                            [base_filter(card_id, kind="benefit_status")],
                            primary="{{ state_attr(entity, 'benefit') }}",
                            secondary=(
                                "{{ states(entity) | replace('_', ' ') "
                                "| replace('n a', 'not applicable') }}"
                                "{% if state_attr(entity, 'amount') %} · "
                                "${{ " + attr("amount_used") + " | round(0) | int }} of "
                                "${{ " + attr("amount") + " | round(0) | int }}"
                                "{% elif state_attr(entity, 'amount_used') %} · "
                                "${{ " + attr("amount_used") + " | round(2) }} back{% endif %}"
                            ),
                            icon="mdi:gift-outline",
                            sort={"method": "friendly_name"},
                            show_empty=True,
                        )
                    ],
                )
            ]
        )
    )

    settings = []
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
    sections.append(
        {
            "type": "grid",
            "cards": [
                expander(heading("Card settings", "mdi:credit-card-settings-outline"), settings)
            ],
        }
    )

    return {
        "type": "sections",
        "title": name,
        "path": slugify(name),
        "icon": "mdi:credit-card",
        "subview": True,
        "theme": THEME,
        "max_columns": 4,
        "sections": sections,
    }


CATALOG_FRAME_STYLE = (
    "ha-card { height: calc(100vh - var(--header-height, 56px) - 16px); "
    "border: none; background: transparent; } "
    "#root { height: 100% !important; padding-top: 0 !important; } "
    "iframe { height: 100%; }"
)


def catalog_view() -> dict:
    """The card catalog as a tab of the dashboard: an iframe over the page the
    integration serves at /cardperks/catalog, filling the view."""
    return {
        "title": "Catalog",
        "path": "catalog",
        "icon": "mdi:credit-card-search-outline",
        "type": "panel",
        "theme": THEME,
        "show_icon_and_title": True,
        "cards": [
            {
                "type": "iframe",
                "url": "/cardperks/catalog",
                "aspect_ratio": "100%",
                "card_mod": {"style": CATALOG_FRAME_STYLE},
            }
        ],
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
    views = [build_view(c) for c in cards] + [catalog_view()]
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(views, fh, indent=2, ensure_ascii=False)
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as fh:
            json.dump(nav_section(cards, "dashboard-cardperks"), fh, indent=2, ensure_ascii=False)
    print(f"{len(views) - 1} subviews plus the Catalog view")
    for c, v in zip(cards, views[:-1], strict=True):
        print(f"  {c['title']:45s} sections={len(v['sections'])} ids={len(c['ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
