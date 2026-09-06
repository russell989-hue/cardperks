#!/usr/bin/env python3
"""Rebuild the generated CardPerks overview sections.

Each section is a template that walks entities by attribute rather than naming them,
so adding or removing a card needs no regeneration.

Colour: Home Assistant's markdown card sanitises inline styles away, so a coloured
`<span>` renders as a plain dot. Emoji survive sanitising, so each card's colour is
shown as the nearest coloured emoji. Tiles elsewhere use the real colour.

Push each with tools/append_section.py, which replaces a section by its heading and
leaves the rest of a hand-edited view alone.

  python3 build_sections.py outdir/
"""

from __future__ import annotations

import json
import pathlib
import sys

# Nearest emoji per Home Assistant tile colour. Circles and squares are used to keep
# neighbouring hues apart, since emoji offer far fewer colours than the palette does.
EMOJI = {
    "red": "🔴",
    "pink": "🟥",
    "purple": "🟣",
    "deep-purple": "🟪",
    "indigo": "🔵",
    "blue": "🟦",
    "light-blue": "🩵",
    "cyan": "🧊",
    "teal": "🟢",
    "green": "🟩",
    "light-green": "🍀",
    "lime": "🟨",
    "yellow": "🟡",
    "amber": "🟧",
    "orange": "🟠",
    "deep-orange": "🔶",
    "brown": "🟤",
    "grey": "⚪",
    "blue-grey": "⬜",
}

EMOJI_MAP = "{%- set EMOJI = " + json.dumps(EMOJI, ensure_ascii=False) + " -%}"
DOT = "{{ EMOJI.get(r.color, '⚪') }}"
# Card titles contain " | " before the last four, which markdown would read as a
# new column. Escaping keeps the pipe visible inside the cell.
ESC = r"| replace('|', '\|')"

# Entities that know a card title and its colour, for lists keyed only by card name.
TINTED = """
{%- set tinted = states.sensor
      | selectattr('attributes.card_id', 'defined')
      | selectattr('attributes.color', 'defined') | list -%}
"""


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def markdown(content: str) -> dict:
    return {"type": "markdown", "content": content}


def rows_from(suffix: str, fields: str) -> str:
    """Collect one row per card-level sensor ending in `suffix`."""
    return f"""
{{%- set ns = namespace(rows=[]) -%}}
{{%- for s in states.sensor -%}}
  {{%- if s.attributes.card_id is defined and s.entity_id.endswith('{suffix}') -%}}
    {{%- set a = s.attributes -%}}
    {{%- set ns.rows = ns.rows + [{{'card': a.card, 'color': a.color, {fields}}}] -%}}
  {{%- endif -%}}
{{%- endfor -%}}
"""


def dollars_left() -> dict:
    body = (
        EMOJI_MAP
        + """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.card_id is defined and s.entity_id.endswith('_remaining') -%}
    {%- set v = s.state | float(-1) -%}
    {%- if v > 0 -%}
      {%- set label = s.name | replace(s.attributes.card ~ ' ', '') | replace(' remaining', '') -%}
      {%- set ns.rows = ns.rows + [{'amt': v, 'card': s.attributes.card,
          'color': s.attributes.color, 'name': label}] -%}
    {%- endif -%}
  {%- endif -%}
{%- endfor -%}

| Benefit | Card | Left |
|---|---|--:|
{% for r in ns.rows | sort(attribute='amt', reverse=true) -%}
| {{ r.name ESC }} | DOT {{ r.card ESC }} | ${{ r.amt | round(0) | int }} |
{% endfor %}
_{{ ns.rows | count }} credits, ${{ ns.rows | sum(attribute='amt') | round(0) | int }} \
still on the table._
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [heading("Dollars left by benefit", "mdi:cash-clock"), markdown(body)],
    }


def by_card() -> dict:
    body = (
        EMOJI_MAP
        + rows_from(
            "_capture_rate",
            "'worth': a.get('annual_value', 0), 'cap': a.get('captured_12m', 0),"
            " 'forf': a.get('forfeited_12m', 0), 'rate': s.state | float(0)",
        )
        + """
Trailing twelve months. Forfeited is money a period closed without you using it.

| Card | A year's worth | Captured | Forfeited | Rate |
|---|--:|--:|--:|--:|
{% for r in ns.rows | sort(attribute='card') -%}
| DOT {{ r.card ESC }} | ${{ r.worth | round(0) | int }} | ${{ r.cap | round(0) | int }} \
| ${{ r.forf | round(0) | int }} | {{ r.rate | round(0) | int }}% |
{% endfor %}
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [heading("By card", "mdi:credit-card-multiple"), markdown(body)],
    }


def fees() -> dict:
    body = (
        EMOJI_MAP
        + rows_from(
            "_annual_fee_due",
            "'fee': a.get('annual_fee', 0), 'due': s.state",
        )
        + """
| Card | Fee | Due | Days |
|---|--:|---|--:|
{% for r in ns.rows | sort(attribute='due') -%}
{%- if r.due not in ['unknown', 'unavailable'] -%}
| DOT {{ r.card ESC }} | ${{ r.fee | round(0) | int }} | {{ r.due }} \
| {{ ((r.due | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }} |
{% endif -%}
{% endfor %}
_${{ ns.rows | sum(attribute='fee') | round(0) | int }} a year across \
{{ ns.rows | count }} cards._
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [heading("Annual fees", "mdi:calendar-cash"), markdown(body)],
    }


def expiring() -> dict:
    body = (
        EMOJI_MAP
        + TINTED
        + """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.owner_id is defined and s.entity_id.endswith('_30_days') -%}
    {%- for i in s.attributes.get('items', []) -%}
      {%- set ns.rows = ns.rows + [i] -%}
    {%- endfor -%}
  {%- endif -%}
{%- endfor -%}
{%- if ns.rows | count == 0 %}
Nothing expires in the next 30 days.
{%- else %}

| Benefit | Card | Left | Days |
|---|---|--:|--:|
{% for i in ns.rows | sort(attribute='expires') -%}
{%- set m = tinted | selectattr('attributes.card', 'eq', i.card) | list -%}
{%- set r = {'color': (m | first).attributes.color if m else 'grey'} -%}
| {{ i.benefit ESC }} | DOT {{ i.card ESC }} | ${{ i.remaining | round(0) | int }} \
| {{ ((i.expires | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }} |
{% endfor -%}
{%- endif -%}
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [heading("Expiring within 30 days", "mdi:timer-sand"), markdown(body)],
    }


def coverage() -> dict:
    body = (
        EMOJI_MAP
        # Matched on an attribute rather than an entity id suffix: entity ids come from
        # the display name, so a rename or a translation change would break a suffix.
        + """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.card_id is defined and s.attributes.missing is defined -%}
    {%- set a = s.attributes -%}
    {%- set ns.rows = ns.rows + [{'card': a.card, 'color': a.color,
        'n': s.state | int(0), 'missing': a.get('missing', []),
        'files': a.get('statements_imported', 0)}] -%}
  {%- endif -%}
{%- endfor -%}
"""
        + """
A month with no statement is unknown, not proof a credit went unused.

| Card | Covered | Files | Gaps |
|---|--:|--:|---|
{% for r in ns.rows | sort(attribute='card') -%}
| DOT {{ r.card ESC }} | {{ r.n }}/12 | {{ r.files }} \
| {% if r.missing | count == 0 %}none{% elif r.missing | count > 4 %}\
{{ r.missing[:3] | join(', ') }} +{{ (r.missing | count) - 3 }} more\
{% else %}{{ r.missing | join(', ') }}{% endif %} |
{% endfor %}
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [
            heading("Statement coverage", "mdi:file-document-check-outline"),
            markdown(body),
        ],
    }


def legend() -> dict:
    """So the emoji in every table can be tied back to a card."""
    body = (
        EMOJI_MAP
        + TINTED
        + """
{%- set ns = namespace(seen=[], rows=[]) -%}
{%- for s in tinted -%}
  {%- if s.attributes.card not in ns.seen -%}
    {%- set ns.seen = ns.seen + [s.attributes.card] -%}
    {%- set ns.rows = ns.rows + [{'card': s.attributes.card, 'color': s.attributes.color}] -%}
  {%- endif -%}
{%- endfor -%}
{% for r in ns.rows | sort(attribute='card') %}DOT {{ r.card }}&nbsp;&nbsp; {% endfor %}
""".replace("DOT", DOT).replace("ESC", ESC)
    )
    return {
        "type": "grid",
        "cards": [heading("Colour key", "mdi:palette"), markdown(body)],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    outdir = pathlib.Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    for name, section in {
        "dollars_left": dollars_left(),
        "by_card": by_card(),
        "fees": fees(),
        "expiring": expiring(),
        "coverage": coverage(),
        "legend": legend(),
    }.items():
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(section, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
