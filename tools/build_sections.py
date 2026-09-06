#!/usr/bin/env python3
"""Rebuild the generated CardPerks overview sections.

These are written as templates that walk entities by attribute rather than naming
them, so a card added or removed later needs no regeneration. Every card's colour is
read from its own entities, which is how the colour reaches lists that Lovelace has
no per-row colour option for.

Push each with tools/append_section.py, which replaces a section by its heading and
leaves the rest of a hand-edited view alone.

  python3 build_sections.py outdir/
"""

from __future__ import annotations

import json
import pathlib
import sys

DOT = "<span style=\"color: var(--{{ r.color or 'grey' }}-color)\">&#9679;</span>"

# Entities that know both a card title and its colour. Home Assistant's template
# sandbox forbids dict.update, so lists keyed by card name look the colour up here.
COLOUR_LOOKUP = """
{%- set tinted = states.sensor
      | selectattr('attributes.card_id', 'defined')
      | selectattr('attributes.color', 'defined') | list -%}
"""

# Every per-benefit "remaining" sensor with a balance, plus a clean benefit name.
BENEFIT_ROWS = """
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
"""


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def markdown(content: str) -> dict:
    return {"type": "markdown", "content": content}


def dollars_left() -> dict:
    body = (
        BENEFIT_ROWS
        + "| Benefit | Card | Left |\n|---|---|--:|\n"
        + "{% for r in ns.rows | sort(attribute='amt', reverse=true) -%}\n"
        + f"| {{{{ r.name }}}} | {DOT} {{{{ r.card }}}} "
        + "| ${{ r.amt | round(0) | int }} |\n"
        + "{% endfor %}\n"
        + "_{{ ns.rows | count }} credits, "
        + "${{ ns.rows | sum(attribute='amt') | round(0) | int }} on the table._"
    )
    return {
        "type": "grid",
        "cards": [heading("Dollars left by benefit", "mdi:cash-clock"), markdown(body)],
    }


def by_card() -> dict:
    body = """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.card_id is defined and s.entity_id.endswith('_capture_rate') -%}
    {%- set a = s.attributes -%}
    {%- set ns.rows = ns.rows + [{'card': a.card, 'color': a.color,
        'worth': a.get('annual_value', 0), 'cap': a.get('captured_12m', 0),
        'forf': a.get('forfeited_12m', 0), 'rate': s.state | float(0)}] -%}
  {%- endif -%}
{%- endfor -%}

| Card | A year's worth | Captured | Forfeited | Rate |
|---|--:|--:|--:|--:|
{% for r in ns.rows | sort(attribute='card') -%}
| DOT {{ r.card }} | ${{ r.worth | round(0) | int }} | ${{ r.cap | round(0) | int }} \
| ${{ r.forf | round(0) | int }} | {{ r.rate | round(0) | int }}% |
{% endfor %}
""".replace("DOT", DOT)
    return {
        "type": "grid",
        "cards": [
            heading("By card", "mdi:credit-card-multiple"),
            markdown(
                "Trailing twelve months. Forfeited is money a period closed without "
                "you using it.\n" + body
            ),
        ],
    }


def expiring() -> dict:
    body = (
        COLOUR_LOOKUP
        + """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.owner_id is defined and s.entity_id.endswith('_30_days') -%}
    {%- for i in s.attributes.get('items', []) -%}
      {%- set ns.rows = ns.rows + [i] -%}
    {%- endfor -%}
  {%- endif -%}
{%- endfor -%}
{%- if ns.rows | count == 0 -%}
Nothing expires in the next 30 days.
{%- else -%}
| Benefit | Card | Left | Days |
|---|---|--:|--:|
{% for i in ns.rows | sort(attribute='expires') -%}
{%- set m = tinted | selectattr('attributes.card', 'eq', i.card) | list -%}
{%- set r = {'color': (m | first).attributes.color if m else 'grey'} -%}
| {{ i.benefit }} | DOT {{ i.card }} | ${{ i.remaining | round(0) | int }} \
| {{ ((i.expires | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }} |
{% endfor -%}
{%- endif -%}
""".replace("DOT", DOT)
    )
    return {
        "type": "grid",
        "cards": [heading("Expiring within 30 days", "mdi:timer-sand"), markdown(body)],
    }


def coverage() -> dict:
    body = """
{%- set ns = namespace(rows=[]) -%}
{%- for s in states.sensor -%}
  {%- if s.attributes.card_id is defined and s.entity_id.endswith('_coverage_12m') -%}
    {%- set a = s.attributes -%}
    {%- set ns.rows = ns.rows + [{'card': a.card, 'color': a.color,
        'n': s.state | int(0), 'missing': a.get('missing', []),
        'files': a.get('statements_imported', 0)}] -%}
  {%- endif -%}
{%- endfor -%}
A month with no statement is unknown, not proof a credit went unused.

| Card | Covered | Files | Gaps |
|---|--:|--:|---|
{% for r in ns.rows | sort(attribute='card') -%}
| DOT {{ r.card }} | {{ r.n }}/12 | {{ r.files }} \
| {% if r.missing | count == 0 %}none{% elif r.missing | count > 4 %}\
{{ r.missing[:3] | join(', ') }} +{{ (r.missing | count) - 3 }} more\
{% else %}{{ r.missing | join(', ') }}{% endif %} |
{% endfor %}
""".replace("DOT", DOT)
    return {
        "type": "grid",
        "cards": [
            heading("Statement coverage", "mdi:file-document-check-outline"),
            markdown(body),
        ],
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
        "expiring": expiring(),
        "coverage": coverage(),
    }.items():
        path = outdir / f"{name}.json"
        path.write_text(json.dumps(section, indent=2), encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
