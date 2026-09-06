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
    ONLY_ACTIVE,
    _template_cards,
    attr,
    auto_cards,
    base_filter,
    donut_by_card,
    gauge_grid,
    half,
    heading,
    missed_list,
    money_bars,
    money_donut,
    money_legend,
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
                    {**with_status(base_filter(), status=s, this_period="> 0"), "domain": "number"}
                    for s in ("unused", "partial")
                ],
                "Credits with money left",
                suffix="used",
            ),
        ]
    )


def by_card() -> dict:
    return wide_section(
        [
            heading("By card", "mdi:credit-card-multiple"),
            note(
                "Where each card's credit dollars went over the trailing twelve months. "
                "Green is captured, red forfeited, grey unknown (months with no statement); "
                "the dim remainder is still open to capture."
            ),
            money_bars(),
        ]
    )


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


BIG_TICKET_MIN = 50  # dollars still on the table
BIG_TICKET_DAYS = 90  # how far ahead to look


def big_ticket_list() -> dict:
    """The credits worth chasing: at least $50 still unused, closing within 90 days,
    soonest first. The 30-day list catches everything; this one is the short list of
    dining, hotel and travel credits you would actually be sorry to lose."""
    return {
        "type": "grid",
        "cards": [
            heading("Big ticket items", "mdi:star-circle-outline"),
            note(
                f"Credits with ${BIG_TICKET_MIN} or more still to use and fewer than "
                f"{BIG_TICKET_DAYS} days to use it, soonest first."
            ),
            auto_cards(
                [
                    with_status(
                        base_filter(kind="benefit_expires"),
                        status=st,
                        remaining=f">= {BIG_TICKET_MIN}",
                        days_left=f"< {BIG_TICKET_DAYS}",
                    )
                    for st in ("unused", "partial")
                ],
                primary="${{ "
                + attr("remaining")
                + " | round(0) | int }} · {{ state_attr(entity, 'benefit') }}",
                secondary=(
                    "{{ state_attr(entity, 'card') }} · closes {{ states(entity) }} · "
                    "{{ state_attr(entity, 'days_left') }} days"
                ),
                icon="mdi:star-circle-outline",
                sort={"method": "attribute", "attribute": "days_left", "numeric": True},
            ),
        ],
    }


def where_big_dollars_went() -> dict:
    """For credits worth $50 or more a period: the trailing year's dollars as a ring
    (captured, forfeited, unknown, still open) and the ones that were forfeited."""
    return wide_section(
        [
            heading("Where the big dollars went", "mdi:chart-donut"),
            note(
                f"Trailing twelve months, credits worth ${BIG_TICKET_MIN} or more a period: "
                "what was captured, what slipped away, what is unknown, what is still open."
            ),
            money_legend(min_amount=BIG_TICKET_MIN),
            half(money_donut(min_amount=BIG_TICKET_MIN)),
            half(missed_list(min_amount=BIG_TICKET_MIN)),
        ]
    )


def big_ticket() -> dict:
    """Both halves in one section, for a dashboard that keeps a single page."""
    top = big_ticket_list()
    bottom = where_big_dollars_went()
    return {"type": "grid", "cards": top["cards"] + bottom["cards"][1:]}


def by_year() -> dict:
    """One table per card: each cardmember year's fee, captured credits, net, and how
    much of the year statements vouch for. Only what statements prove; nothing about
    what was on offer in past years."""
    template = (
        "{% set ns = namespace(cards=[]) %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'net_value_12m' "
        f"and {ONLY_ACTIVE} and (s.attributes.get('years') or []) | count > 0 %}}"
        "{% set ns.rows = [] %}"
        "{% set ns.text = '**' ~ s.attributes.get('card') ~ '**\\n\\n"
        "| Year | Fee | Captured | Net | Statements |\\n|---|---:|---:|---:|---|\\n' %}"
        "{% for y in s.attributes.get('years') %}"
        "{% set label = (y.start[:4] ~ '-' ~ y.end[:4]) if y.start[:4] != y.end[:4] else y.start[:4] %}"
        "{% set fee = ('$' ~ (y.fee | round(0) | int)) if y.fee is not none else 'not seen' %}"
        "{% set net = (('-' if y.net < 0 else '') ~ '$' ~ (y.net | abs | round(0) | int)) "
        "if y.net is not none else '' %}"
        "{% set ns.text = ns.text ~ '| ' ~ label ~ (' (so far)' if y.current else '') ~ ' | ' ~ fee "
        "~ ' | $' ~ (y.captured | round(0) | int) ~ ' | ' ~ net ~ ' | ' ~ y.months_covered ~ '/' "
        "~ y.months ~ ' months |\\n' %}"
        "{% endfor %}"
        "{% set ns.cards = ns.cards + [{'type': 'markdown', 'content': ns.text, "
        "'sort': s.attributes.get('card')}] %}"
        "{% endfor %}"
        "{{ ns.cards | sort(attribute='sort') }}"
    )
    return wide_section(
        [
            heading("By year", "mdi:calendar-multiple"),
            note(
                "Each cardmember year: the fee a statement showed, the credits recorded, and the "
                'net. "Statements" says how much of the year a statement covers; a thin year is '
                "not a bad year. Nothing is claimed about what was on offer back then."
            ),
            _template_cards(template, columns=2),
        ]
    )


def shared_perks() -> dict:
    """Every perk valued once for the household: what it is worth, each card's share,
    and which cards carry it. Tapping a row edits the household number."""
    return {
        "type": "grid",
        "cards": [
            heading("Shared across cards", "mdi:tag-multiple-outline"),
            note(
                "One membership, several cards. Each of these is one number for the household, "
                "split equally between the cards that carry it. A shared perk only one of your "
                "cards carries is listed under that card instead."
            ),
            _template_cards(
                "{% set ns = namespace(cards=[]) %}"
                "{% for s in states.number if s.attributes.get('kind') == 'shared_value' "
                "and (s.attributes.get('card_ids') or []) | count > 1 %}"
                "{% set ns.cards = ns.cards + [{'type': 'custom:mushroom-template-card', "
                "'entity': s.entity_id, "
                "'primary': '$' ~ (s.state | float(0) | round(0) | int) ~ ' · ' "
                "~ s.attributes.get('benefit'), "
                "'secondary': '$' ~ ((s.attributes.get('per_card') or 0) | round(0) | int) "
                "~ ' each on ' ~ (s.attributes.get('cards') | count) ~ ' cards: ' "
                "~ (s.attributes.get('cards') | join(', ')), "
                "'icon': 'mdi:tag-multiple-outline', 'icon_color': 'amber', "
                "'multiline_secondary': true, 'sort': -(s.state | float(0))}] %}"
                "{% endfor %}"
                "{{ ns.cards | sort(attribute='sort') }}"
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
            note(
                "Lounge access and status carry no issuer amount, so the value is your call. "
                "A perk several cards share (Priority Pass) is one number for all cards, "
                "split equally between them."
            ),
            *peek_rows(
                [
                    {**with_status(base_filter(), kind="perk_value"), "domain": "number"},
                    {**with_status(base_filter(), kind="shared_value"), "domain": "number"},
                ],
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
                maximum=f"(([{annual} - {fee}, 1 - {fee}] | max) | round(2))",
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
        "big_ticket": big_ticket(),
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
