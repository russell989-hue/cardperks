#!/usr/bin/env python3
"""Rebuild the CardPerks overview sections that are generated rather than hand-edited.

Reads the live entity map (tools/cp_full.py output on the HA box) so nothing is
hardcoded, and writes one JSON file per section. push with tools/append_section.py,
which replaces a section by its heading and leaves everything else alone.

  python3 build_sections.py cards.json outdir/
"""

from __future__ import annotations

import json
import pathlib
import sys

# Card colours come from the integration, so a card reads the same on every card.
DOT = '<span style="color: var(--{color}-color)">&#9679;</span>'


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def fees_section(cards: dict) -> dict:
    """Card, fee amount, due date and days out. The amount is the point of the table."""
    rows = []
    for c in sorted(cards.values(), key=lambda c: c["title"] or ""):
        fee_due = c["card"].get("fee_due")
        if not fee_due:
            continue
        dot = DOT.format(color=c["color"] or "grey")
        rows.append(
            f"{{% set s = states['{fee_due}'] %}}"
            f"{{% if s.state not in ['unknown', 'unavailable'] %}}"
            f"| {dot} {c['title']} "
            f"| ${{{{ (s.attributes.annual_fee or 0) | round(0) | int }}}} "
            f"| {{{{ s.state }}}} "
            f"| {{{{ ((s.state | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }}}} |"
            f"{{% endif %}}"
        )
    content = (
        "| Card | Fee | Due | Days |\n|---|--:|---|--:|\n"
        + "\n".join(rows)
        + "\n\n_Total: ${{ "
        + " + ".join(
            f"(state_attr('{c['card']['fee_due']}', 'annual_fee') or 0)"
            for c in cards.values()
            if c["card"].get("fee_due")
        )
        + " | round(0) | int }} a year_"
    )
    return {
        "type": "grid",
        "cards": [
            heading("Annual fees", "mdi:calendar-cash"),
            {"type": "markdown", "content": content},
        ],
    }


def perk_values_section(cards: dict) -> dict:
    """Editable dollar boxes grouped by card.

    A markdown table cannot hold an input, so the card is the group and the perk name
    is the row: it reads as a table but each value stays typable.
    """
    out: list[dict] = [
        heading("What perks are worth to you", "mdi:tag-text-outline"),
        {
            "type": "markdown",
            "text_only": True,
            "content": (
                "Lounge access, elite status and insurance carry no issuer amount. "
                "Type what each is worth to you and every total updates."
            ),
        },
    ]
    for c in sorted(cards.values(), key=lambda c: c["title"] or ""):
        if not c["perks"]:
            continue
        dot = DOT.format(color=c["color"] or "grey")
        # A coloured dot beside the group title ties this block to the card everywhere else.
        out.append({"type": "markdown", "text_only": True, "content": f"{dot} **{c['title']}**"})
        out.append(
            {
                "type": "entities",
                "entities": [{"entity": p["entity"], "name": p["benefit"]} for p in c["perks"]],
            }
        )
    return {"type": "grid", "cards": out}


def annual_dollars_section(cards: dict) -> dict:
    """The whole point: a year's worth, what was captured, what was lost."""
    rows = []
    for c in sorted(cards.values(), key=lambda c: c["title"] or ""):
        rate = c["card"].get("capture_rate")
        if not rate:
            continue
        dot = DOT.format(color=c["color"] or "grey")
        rows.append(
            f"{{% set s = states['{rate}'] %}}"
            f"{{% if s.state not in ['unknown', 'unavailable'] %}}"
            f"| {dot} {c['title']} "
            f"| ${{{{ (s.attributes.annual_value or 0) | round(0) | int }}}} "
            f"| ${{{{ (s.attributes.captured_12m or 0) | round(0) | int }}}} "
            f"| ${{{{ (s.attributes.forfeited_12m or 0) | round(0) | int }}}} "
            f"| {{{{ s.state | round(0) | int }}}}% |"
            f"{{% endif %}}"
        )
    content = (
        "Trailing twelve months. Forfeited is money a period closed without you using, "
        "which is gone rather than pending.\n\n"
        "| Card | A year's worth | Captured | Forfeited | Rate |\n|---|--:|--:|--:|--:|\n"
        + "\n".join(rows)
    )
    return {
        "type": "grid",
        "cards": [
            heading("Annual dollars", "mdi:cash-100"),
            {"type": "markdown", "content": content},
        ],
    }


def checkoff_section() -> dict:
    """Type what you captured. Filtered to benefits with money still on them."""
    return {
        "type": "grid",
        "cards": [
            heading("Check off", "mdi:cash-check"),
            {
                "type": "custom:auto-entities",
                "card": {"type": "entities", "title": "Credits with money left"},
                "show_empty": False,
                "filter": {
                    "include": [
                        {
                            "integration": "cardperks",
                            "domain": "number",
                            "attributes": {"status": s},
                        }
                        for s in ("unused", "partial")
                    ],
                    "exclude": [{"state": "unavailable"}, {"state": "unknown"}],
                },
                "sort": {"method": "friendly_name"},
            },
        ],
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    cards = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = pathlib.Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    sections = {
        "fees": fees_section(cards),
        "perk_values": perk_values_section(cards),
        "annual_dollars": annual_dollars_section(cards),
        "checkoff": checkoff_section(),
    }
    for name, section in sections.items():
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(section, indent=2), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
