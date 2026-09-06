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


def gauge_grid(kind: str, *, columns: int = 2, unit_max: int = 100) -> dict:
    """auto-entities feeding a grid of gauge cards, one per active card.

    Built by a template so a new card appears by itself and each gauge takes its
    card's colour live. The gauge card colours its arc with --gauge-color, which it
    sets inline to --info-color when no severity is configured, so both are overridden.
    """
    where = f"s.attributes.kind == '{kind}' and s.attributes.card_status == 'active'"
    style = (
        "'ha-card { --info-color: var(--' ~ c ~ '-color); } "
        "ha-gauge { --gauge-color: var(--' ~ c ~ '-color) !important; }'"
    )
    template = (
        "{% set ns = namespace(cards=[]) %}"
        f"{{% for s in states.sensor if s.state not in ['unavailable', 'unknown'] and {where} %}}"
        "{% set c = s.attributes.color or 'grey' %}"
        "{% set ns.cards = ns.cards + [{'type': 'gauge', 'entity': s.entity_id, "
        f"'name': s.attributes.card, 'min': 0, 'max': {unit_max}, "
        "'card_mod': {'style': " + style + "}}] %}"
        "{% endfor %}{{ ns.cards | sort(attribute='name') }}"
    )
    return {
        "type": "custom:auto-entities",
        "card": {"type": "grid", "columns": columns, "square": False},
        "card_param": "cards",
        "filter": {"template": template},
    }


def coloured_row(entity: str, name: str) -> dict:
    """An explicit entity row whose icon takes the card colour."""
    return {"entity": entity, "name": name, "card_mod": {"style": ROW_STYLE}}


DAYS_UNTIL = (
    "{{ ((states(entity) | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }}"
)
DOLLARS = "${{ states(entity) | float(0) | round(0) | int }}"


def attr(name: str, default: str = "0") -> str:
    return f"(state_attr(entity, '{name}') or {default})"
