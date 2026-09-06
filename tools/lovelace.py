"""Shared building blocks for the generated CardPerks dashboards.

Colour is read live from each entity's `color` attribute, so one change in the card
form reaches every dashboard without regenerating anything:

- Tiles and multi-field rows are Mushroom template cards, whose `icon_color` is a
  template over the attribute.
- Plain entity rows (the dollar boxes, which must stay editable) get card-mod, which
  colours the row icon from the same attribute.

Both custom cards are installed through HACS on this instance.
"""

from __future__ import annotations

# Mushroom accepts the same palette names Home Assistant tiles do.
ICON_COLOR = "{{ state_attr(entity, 'color') or 'grey' }}"

# card-mod on an entity row: `config.entity` is the row's entity.
ROW_STYLE = (
    ":host {\n"
    "  --paper-item-icon-color: var(--{{ state_attr(config.entity, 'color') or 'grey' }}-color);\n"
    "  --state-icon-color: var(--{{ state_attr(config.entity, 'color') or 'grey' }}-color);\n"
    "}\n"
)


def heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "heading_style": "title", "icon": icon}


def note(text: str) -> dict:
    return {"type": "markdown", "text_only": True, "content": text}


def base_filter(card_id: str | None = None, **attrs: str) -> dict:
    """An auto-entities rule made only of attribute matches.

    Every CardPerks entity carries `kind`, `card_id` and `card_status`, so any list can
    be expressed as attribute rules alone. The auto-entities visual editor can show
    those; it cannot show integration or wildcard entity-id rules, and marks them
    "Unknown". Matching on the card id also survives a device rename.
    """
    attributes = dict(attrs)
    if card_id:
        attributes["card_id"] = card_id
    return {"attributes": attributes} if attributes else {}


def template_card(
    primary: str,
    secondary: str,
    icon: str,
    *,
    entity: str | None = None,
    tap: dict | None = None,
) -> dict:
    card = {
        "type": "custom:mushroom-template-card",
        "primary": primary,
        "secondary": secondary,
        "icon": icon,
        "icon_color": ICON_COLOR,
        "multiline_secondary": True,
    }
    if entity:
        card["entity"] = entity
    if tap:
        card["tap_action"] = tap
    return card


def auto_cards(
    includes: list[dict],
    primary: str,
    secondary: str,
    icon: str,
    *,
    sort: dict | None = None,
    show_empty: bool = False,
) -> dict:
    """auto-entities feeding a column of Mushroom template cards.

    Each include rule gets the Mushroom card as its `options`, and auto-entities adds
    `entity` to it, which the templates read.
    """
    options = template_card(primary, secondary, icon)
    return {
        "type": "custom:auto-entities",
        "card": {"type": "grid", "columns": 1, "square": False},
        "card_param": "cards",
        "show_empty": show_empty,
        "filter": {
            "include": [{**inc, "options": options} for inc in includes],
            "exclude": [{"state": "unavailable"}, {"state": "unknown"}],
        },
        "sort": sort or {"method": "state", "numeric": True, "reverse": True},
    }


def _jinja_where(inc: dict) -> str:
    """One include rule as a Jinja condition over a state object `s`."""
    parts = ["s.attributes.card_id is defined"]
    for key, val in inc.get("attributes", {}).items():
        parts.append(f"s.attributes.{key} == {val!r}")
    if "state" in inc:
        parts.append(f"(s.state | float(0)) {inc['state']}")
    return " and ".join(parts)


def auto_rows(
    includes: list[dict],
    title: str | None = None,
    *,
    suffix: str = "",
    show_empty: bool = False,
) -> dict:
    """auto-entities feeding entity rows, each icon coloured by its card.

    Home Assistant names every entity "<card> <benefit> ...", card first. These lists
    read benefit first, so the rows are built by a template that labels each one
    "<benefit> <suffix>: <card>" from the entity's own attributes, and colours its icon
    from the same place. Rows sort by that label.

    Each include rule may carry `domain`, `attributes` (equality) and `state` (a
    comparison such as "> 0"); rules are OR-ed together.
    """
    card: dict = {"type": "entities", "state_color": True}
    if title:
        card["title"] = title
    domains = sorted({inc.get("domain", "number") for inc in includes})
    where = " or ".join(f"({_jinja_where(inc)})" for inc in includes) or "true"
    label = (
        "s.attributes.benefit ~ '" + (f" {suffix}" if suffix else "") + ": ' ~ s.attributes.card"
    )
    style = (
        "':host { --paper-item-icon-color: var(--' ~ c ~ '-color); "
        "--state-icon-color: var(--' ~ c ~ '-color); }'"
    )
    loops = "".join(
        f"{{% for s in states.{d} if s.state not in ['unavailable', 'unknown'] and ({where}) %}}"
        "{% set c = s.attributes.color or 'grey' %}"
        "{% set ns.rows = ns.rows + [{'entity': s.entity_id, 'name': " + label + ", "
        "'card_mod': {'style': " + style + "}}] %}"
        "{% endfor %}"
        for d in domains
    )
    template = (
        "{% set ns = namespace(rows=[]) %}" + loops + "{{ ns.rows | sort(attribute='name') }}"
    )
    return {
        "type": "custom:auto-entities",
        "card": card,
        "show_empty": show_empty,
        "filter": {"template": template},
    }


def gauge_grid(
    kind: str,
    *,
    name: str = "s.attributes.card",
    minimum: str = "0",
    maximum: str = "100",
    where: str = "",
    by_value: bool = False,
    columns: int = 2,
) -> dict:
    """auto-entities feeding a grid of gauge cards, one per matching entity.

    Built by a template so new cards and benefits appear by themselves and each
    gauge takes its card's colour live. `name`, `minimum` and `maximum` are Jinja expressions
    over the state object `s`; `where` is an extra condition. Sorted by name, or by
    value (largest first) when `by_value` is set.

    The gauge card colours its arc with --gauge-color, which it sets inline to
    --info-color when no severity is configured, so both are overridden.
    """
    cond = f"s.attributes.kind == '{kind}' and s.attributes.card_status == 'active'"
    if where:
        cond += f" and ({where})"
    style = (
        "'ha-card { --info-color: var(--' ~ c ~ '-color); } "
        "ha-gauge { --gauge-color: var(--' ~ c ~ '-color) !important; }'"
    )
    template = (
        "{% set ns = namespace(items=[]) %}"
        f"{{% for s in states.sensor if s.state not in ['unavailable', 'unknown'] and {cond} %}}"
        "{% set c = s.attributes.color or 'grey' %}"
        "{% set ns.items = ns.items + [[s.state | float(0), {'type': 'gauge', "
        f"'entity': s.entity_id, 'name': {name}, 'min': {minimum}, 'max': {maximum}, "
        "'card_mod': {'style': " + style + "}}]] %}"
        "{% endfor %}"
        + (
            "{{ ns.items | sort(attribute='0', reverse=true) | map(attribute='1') | list }}"
            if by_value
            else "{{ ns.items | map(attribute='1') | sort(attribute='name') | list }}"
        )
    )
    return {
        "type": "custom:auto-entities",
        "card": {"type": "grid", "columns": columns, "square": False},
        "card_param": "cards",
        "filter": {"template": template},
    }


# What is left to use, gathered once for the ring and its centre label:
#   ns.cards  [dollars, card_id, colour] per active card with money left
#   ns.rems   [dollars, card_id] per benefit with money left
#   ns.total  the sum of those benefits
_LEFT_TO_USE = (
    "{% set ns = namespace(total=0.0, cards=[], rems=[], acc=0.0, out=[]) %}"
    "{% for s in states.sensor if s.attributes.kind == 'unused_value' "
    "and s.attributes.card_status == 'active' "
    "and s.state not in ['unknown', 'unavailable'] and (s.state | float(0)) > 0 %}"
    "{% set ns.cards = ns.cards + [[s.state | float(0), s.attributes.card_id, "
    "s.attributes.color or 'grey']] %}"
    "{% endfor %}"
    "{% for r in states.sensor if r.attributes.kind == 'benefit_remaining' "
    "and r.attributes.card_status == 'active' "
    "and r.state not in ['unknown', 'unavailable'] and (r.state | float(0)) > 0 %}"
    "{% set ns.rems = ns.rems + [[r.state | float(0), r.attributes.card_id]] %}"
    "{% set ns.total = ns.total + (r.state | float(0)) %}"
    "{% endfor %}"
)


def donut_by_card(size: int = 240) -> dict:
    """One ring of the dollars left to use: a slice per card, subdivided by benefit.

    Cards run largest first; within a card each benefit is a segment, largest first,
    in a shade of the card's colour that steps from full strength down to about half,
    mixed towards the card background so it works in either theme.

    A Markdown card: card-mod paints its background as a conic gradient computed by a
    template, lays a disc of card background over the centre, and the card's own
    content prints the total in the middle. All live; nothing to install beyond
    card-mod. Shades use CSS color-mix, which every current browser supports.
    """
    slices = (
        _LEFT_TO_USE + "{% for c in ns.cards | sort(attribute='0', reverse=true) %}"
        "{% set parts = ns.rems | selectattr('1', 'eq', c[1]) "
        "| sort(attribute='0', reverse=true) | list %}"
        "{% set n = parts | count %}"
        "{% for p in parts %}"
        "{% set pct = p[0] / ns.total * 100 %}"
        "{% set mix = (100 - loop.index0 * 55 / ([n - 1, 1] | max)) | round(0) | int %}"
        "{% set ns.out = ns.out + ['color-mix(in srgb, var(--' ~ c[2] ~ '-color) ' ~ mix "
        "~ '%, var(--card-background-color)) ' ~ (ns.acc | round(2)) ~ '% ' "
        "~ ((ns.acc + pct) | round(2)) ~ '%'] %}"
        "{% set ns.acc = ns.acc + pct %}"
        "{% endfor %}{% endfor %}"
        "{{ ns.out | join(', ') if ns.out else 'var(--divider-color) 0% 100%' }}"
    )
    style = (
        "ha-card {\n"
        f"  width: {size}px; height: {size}px; border-radius: 50%; margin: 8px auto;\n"
        "  box-sizing: border-box; border: none; box-shadow: none;\n"
        "  display: flex; align-items: center; justify-content: center;\n"
        "  text-align: center; font-size: 1.15em;\n"
        "  background:\n"
        "    radial-gradient(circle, var(--ha-card-background, var(--card-background-color)) 58%, "
        "transparent 59%),\n"
        "    conic-gradient(" + slices + ");\n"
        "}\n"
        "ha-markdown { padding: 0 28px; }\n"
    )
    content = (
        _LEFT_TO_USE + "**${{ ns.total | round(0) | int }}**<br>left to use<br>"
        "{{ ns.rems | count }} credits on {{ ns.cards | count }} card"
        "{{ '' if ns.cards | count == 1 else 's' }}"
    )
    return {"type": "markdown", "content": content, "card_mod": {"style": style}}


def coloured_row(entity: str, name: str) -> dict:
    """An explicit entity row whose icon takes the card colour."""
    return {"entity": entity, "name": name, "card_mod": {"style": ROW_STYLE}}


DAYS_UNTIL = (
    "{{ ((states(entity) | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }}"
)
DOLLARS = "${{ states(entity) | float(0) | round(0) | int }}"


def attr(name: str, default: str = "0") -> str:
    return f"(state_attr(entity, '{name}') or {default})"
