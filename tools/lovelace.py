"""Shared building blocks for the generated CardPerks dashboards.

Colour is read live from each entity's `color` attribute, so one change in the card
form reaches every dashboard without regenerating anything:

- Tiles and multi-field rows are Mushroom template cards, whose `icon_color` is a
  template over the attribute.
- Plain entity rows (the dollar boxes, which must stay editable) get card-mod, which
  colours the row icon from the same attribute.
- Rings, bars and gauges are built by auto-entities templates, so a new card or
  benefit appears by itself, and card-mod paints them from the same attribute.

Every template reads attributes with .get(), because the markdown card renders in
strict mode and errors on an attribute a sensor lacks. auto-entities, Mushroom,
card-mod and expander-card are installed through HACS on this instance.
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

DAYS_UNTIL = (
    "{{ ((states(entity) | as_timestamp - now() | as_timestamp) / 86400) | round(0) | int }}"
)
DOLLARS = "${{ states(entity) | float(0) | round(0) | int }}"

# Only entities of one card, as a Jinja condition over the state object `s`.
ONLY_CARD = "s.attributes.get('card_id') == '{card_id}'"
ONLY_ACTIVE = "s.attributes.get('card_status') == 'active'"

# Tapping anything that belongs to a card opens that card's own view. The path is the
# card title slugified the way build_card_views.py names the subviews.
DASHBOARD = "dashboard-cardperks"
CARD_PATH = f"'/{DASHBOARD}/' ~ (s.attributes.get('card') | slugify | replace('_', '-'))"
NAVIGATE = "{'action': 'navigate', 'navigation_path': " + CARD_PATH + "}"


def _inner(tpl: str) -> str:
    """A Mushroom template, quoted to sit inside an outer Jinja string literal.

    The outer template builds card configs; the Mushroom card renders these later,
    with `entity` set. Jinja leaves them alone inside a single-quoted literal as long
    as they use double quotes themselves.
    """
    assert '"' not in tpl, tpl
    return tpl.replace("'", '"')


# Net value gauge: from paying the fee for nothing, to capturing everything. The
# annual value lives on the capture-rate sensor, so it is looked up by card id.
_FEE = "(s.attributes.get('annual_fee') or 0)"
_ANNUAL = (
    "((states.sensor | selectattr('attributes.kind', 'defined') "
    "| selectattr('attributes.kind', 'eq', 'capture_rate') "
    "| selectattr('attributes.card_id', 'eq', s.attributes.get('card_id')) "
    "| map(attribute='attributes.annual_value') | list | first) or 0)"
)
NET_MIN = f"-{_FEE}"
NET_MAX = f"(([{_ANNUAL} - {_FEE}, 1 - {_FEE}] | max) | round(2))"


def attr(name: str, default: str = "0") -> str:
    return f"(state_attr(entity, '{name}') or {default})"


# ------------------------------------------------------------------ plain cards


HEADING_STYLE = (
    ".title { font-family: var(--ha-font-family-heading, Georgia, serif); "
    "font-weight: 600; letter-spacing: -0.01em; }"
)


def heading(text: str, icon: str) -> dict:
    """A section heading in the theme's serif. The heading card sizes its title from
    theme variables but not the family, so card-mod supplies it."""
    return {
        "type": "heading",
        "heading": text,
        "heading_style": "title",
        "icon": icon,
        "card_mod": {"style": HEADING_STYLE},
    }


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


def coloured_row(entity: str, name: str) -> dict:
    """An explicit entity row whose icon takes the card colour."""
    return {"entity": entity, "name": name, "card_mod": {"style": ROW_STYLE}}


# ------------------------------------------------------------------ layout


def full_width(card: dict) -> dict:
    """Span the whole section, which matters once the section is two columns wide."""
    return {**card, "grid_options": {"columns": "full"}}


def half(card: dict) -> dict:
    return {**card, "grid_options": {"columns": 12}}


def third(card: dict) -> dict:
    return {**card, "grid_options": {"columns": 8}}


def wide_section(cards: list[dict], *, halves: int = 0) -> dict:
    """A section spanning two dashboard columns.

    Cards without their own grid options span the full width; the last `halves`
    cards sit side by side. Lists with long labels and dollar boxes need the room.
    """
    head = cards[: len(cards) - halves] if halves else cards
    tail = cards[len(cards) - halves :] if halves else []
    return {
        "type": "grid",
        "column_span": 2,
        "cards": [c if "grid_options" in c else full_width(c) for c in head] + tail,
    }


def expander(title: dict, cards: list[dict], *, expanded: bool = False) -> dict:
    """Fold cards behind a title card (HACS expander-card).

    With a heading as the title card the section keeps its look, the push tools still
    find the section by that heading, and clicking it toggles.
    """
    return {
        "type": "custom:expander-card",
        "title-card": title,
        "title-card-clickable": True,
        "title-card-button-overlay": True,
        "expanded": expanded,
        "clear": True,
        "child-padding": "0",
        "gap": "0.6em",
        "cards": cards,
    }


# ------------------------------------------------------------------ auto-entities lists


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

    Built by a template rather than include/options so that each card can carry a
    tap action to its own card's view, which needs the card title at build time. The
    Mushroom templates for the text still run in the Mushroom card, with `entity` set.
    `sort` takes the auto-entities shape: method state|attribute, attribute, numeric,
    reverse.
    """
    sort = sort or {"method": "state", "numeric": True, "reverse": True}
    if sort.get("method") == "attribute":
        key = f"s.attributes.get('{sort['attribute']}')"
    else:
        key = "s.state"
    key = f"({key} | float(0))" if sort.get("numeric") else f"({key} | string)"
    reverse = "true" if sort.get("reverse") else "false"
    domains, where = _rows_query(
        [{**inc, "domain": inc.get("domain", "sensor")} for inc in includes]
    )
    card = (
        "{'type': 'custom:mushroom-template-card', 'entity': s.entity_id, "
        f"'primary': '{_inner(primary)}', 'secondary': '{_inner(secondary)}', "
        f"'icon': '{_inner(icon)}', 'icon_color': '{_inner(ICON_COLOR)}', "
        f"'multiline_secondary': true, 'tap_action': {NAVIGATE}, 'sort': {key}}}"
    )
    loops = "".join(
        f"{{% for s in states.{d} if s.state not in ['unavailable', 'unknown'] and ({where}) %}}"
        f"{{% set ns.cards = ns.cards + [{card}] %}}{{% endfor %}}"
        for d in domains
    )
    template = (
        "{% set ns = namespace(cards=[]) %}"
        + loops
        + f"{{{{ ns.cards | sort(attribute='sort', reverse={reverse}) }}}}"
    )
    return {
        "type": "custom:auto-entities",
        "card": {"type": "grid", "columns": 1, "square": False},
        "card_param": "cards",
        "show_empty": show_empty,
        "filter": {"template": template},
    }


def _jinja_where(inc: dict) -> str:
    """One include rule as a Jinja condition over a state object `s`."""
    parts = ["s.attributes.get('card_id') is not none"]
    for key, val in inc.get("attributes", {}).items():
        if isinstance(val, str) and (val[:1] in "<>" or val[:2] in ("==", "!=")):
            # a comparison such as "> 0", the same shorthand auto-entities accepts
            parts.append(f"(s.attributes.get('{key}') | float(0)) {val}")
        else:
            parts.append(f"s.attributes.get('{key}') == {val!r}")
    if "state" in inc:
        val = str(inc["state"])
        if val[:1] in "<>" or val[:2] in ("==", "!="):
            parts.append(f"(s.state | float(0)) {val}")
        else:
            parts.append(f"s.state == {val!r}")
    return " and ".join(parts)


def _rows_query(includes: list[dict]) -> tuple[list[str], str]:
    """Domains to scan and the OR-ed Jinja condition for a set of include rules."""
    domains = sorted({inc.get("domain", "number") for inc in includes})
    where = " or ".join(f"({_jinja_where(inc)})" for inc in includes) or "true"
    return domains, where


def _template_cards(template: str, *, columns: int = 1, show_empty: bool = False) -> dict:
    """auto-entities whose template yields whole card configs, laid out in a grid."""
    return {
        "type": "custom:auto-entities",
        "card": {"type": "grid", "columns": columns, "square": False},
        "card_param": "cards",
        "show_empty": show_empty,
        "filter": {"template": template},
    }


def auto_rows(
    includes: list[dict],
    title: str | None = None,
    *,
    suffix: str = "",
    show_empty: bool = False,
    rows: tuple[int | None, int | None] | None = None,
) -> dict:
    """auto-entities feeding entity rows, each icon coloured by its card.

    Home Assistant names every entity "<card> <benefit> ...", card first. These lists
    read benefit first, so the rows are built by a template that labels each one
    "<benefit> <suffix>: <card>" from the entity's own attributes, and colours its icon
    from the same place. Rows sort by that label.

    Each include rule may carry `domain`, `attributes` (equality) and `state` (a
    comparison such as "> 0"); rules are OR-ed together. `rows` takes a (start, stop)
    slice of the sorted list, so one list can be shown in parts.
    """
    card: dict = {"type": "entities", "state_color": True}
    if title:
        card["title"] = title
    domains, where = _rows_query(includes)
    label = (
        "s.attributes.get('benefit') ~ '"
        + (f" {suffix}" if suffix else "")
        + ": ' ~ s.attributes.get('card')"
    )
    style = (
        "':host { --paper-item-icon-color: var(--' ~ c ~ '-color); "
        "--state-icon-color: var(--' ~ c ~ '-color); }'"
    )
    loops = "".join(
        f"{{% for s in states.{d} if s.state not in ['unavailable', 'unknown'] and ({where}) %}}"
        "{% set c = s.attributes.get('color') or 'grey' %}"
        "{% set ns.rows = ns.rows + [{'entity': s.entity_id, 'name': " + label + ", "
        "'tap_action': " + NAVIGATE + ", "
        "'card_mod': {'style': " + style + "}}] %}"
        "{% endfor %}"
        for d in domains
    )
    window = ""
    if rows is not None:
        start, stop = rows
        window = f"[{'' if start is None else start}:{'' if stop is None else stop}]"
    template = (
        "{% set ns = namespace(rows=[]) %}"
        + loops
        + "{{ (ns.rows | sort(attribute='name'))"
        + window
        + " }}"
    )
    return {
        "type": "custom:auto-entities",
        "card": card,
        "show_empty": show_empty,
        "filter": {"template": template},
    }


def perk_rows_for_card(card_id: str) -> dict:
    """The perk value boxes for one card: its own perks, then the household numbers for
    the perks it shares, labelled with this card's share. Built by a template so a perk
    that becomes shared (or stops being) needs no regeneration."""
    own = (
        "{% for s in states.number if s.attributes.get('kind') == 'perk_value' "
        f"and {ONLY_CARD.format(card_id=card_id)} %}}"
        "{% set c = s.attributes.get('color') or 'grey' %}"
        "{% set ns.rows = ns.rows + [{'entity': s.entity_id, "
        "'name': s.attributes.get('benefit') ~ ' value', "
        "'card_mod': {'style': ':host { --paper-item-icon-color: var(--' ~ c ~ '-color); "
        "--state-icon-color: var(--' ~ c ~ '-color); }'}}] %}"
        "{% endfor %}"
    )
    shared = (
        "{% for s in states.number if s.attributes.get('kind') == 'shared_value' "
        f"and '{card_id}' in (s.attributes.get('card_ids') or []) %}}"
        "{% set ns.rows = ns.rows + [{'entity': s.entity_id, "
        "'name': s.attributes.get('benefit') ~ ' value, all cards ($' "
        "~ ((s.attributes.get('per_card') or 0) | round(0) | int) ~ ' this card)'}] %}"
        "{% endfor %}"
    )
    template = (
        "{% set ns = namespace(rows=[]) %}"
        + own
        + shared
        + "{{ ns.rows | sort(attribute='name') }}"
    )
    return {
        "type": "custom:auto-entities",
        "card": {"type": "entities"},
        "show_empty": False,
        "filter": {"template": template},
    }


def peek_rows(
    includes: list[dict],
    title: str,
    *,
    suffix: str = "",
    peek: int = 3,
    noun: str = "credits",
) -> list[dict]:
    """One row list shown in two parts: the first `peek` rows, then the rest folded
    behind an expander whose title counts what is hidden ("42 more credits")."""
    domains, where = _rows_query(includes)
    count = (
        "{% set ns = namespace(n=0) %}"
        + "".join(
            f"{{% for s in states.{d} if s.state not in ['unavailable', 'unknown'] "
            f"and ({where}) %}}{{% set ns.n = ns.n + 1 %}}{{% endfor %}}"
            for d in domains
        )
        + f"{{{{ [ns.n - {peek}, 0] | max }}}} more {noun}"
    )
    more = {
        "type": "custom:mushroom-template-card",
        "primary": count,
        "icon": "mdi:unfold-more-horizontal",
        "icon_color": "grey",
        "tap_action": {"action": "none"},
    }
    return [
        auto_rows(includes, title, suffix=suffix, rows=(0, peek), show_empty=True),
        expander(more, [auto_rows(includes, suffix=suffix, rows=(peek, None))]),
    ]


# ------------------------------------------------------------------ graphs


def gauge_grid(
    kind: str,
    *,
    name: str = "s.attributes.get('card')",
    minimum: str = "0",
    maximum: str = "100",
    where: str = "",
    by_value: bool = False,
    columns: int = 2,
) -> dict:
    """auto-entities feeding a grid of gauge cards, one per matching entity.

    Built by a template so new cards appear by themselves and each gauge takes its
    card's colour live. `name`, `minimum` and `maximum` are Jinja expressions over the
    state object `s`; `where` is an extra condition. Sorted by name, or by value
    (largest first) when `by_value` is set.

    The gauge card colours its arc with --gauge-color, which it sets inline to
    --info-color when no severity is configured, so both are overridden.
    """
    cond = f"s.attributes.get('kind') == '{kind}' and {ONLY_ACTIVE}"
    if where:
        cond += f" and ({where})"
    style = (
        "'ha-card { --info-color: var(--' ~ c ~ '-color); } "
        "ha-gauge { --gauge-color: var(--' ~ c ~ '-color) !important; }'"
    )
    template = (
        "{% set ns = namespace(items=[]) %}"
        f"{{% for s in states.sensor if s.state not in ['unavailable', 'unknown'] and {cond} %}}"
        "{% set c = s.attributes.get('color') or 'grey' %}"
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
    return _template_cards(template, columns=columns)


def _left_to_use(card_id: str | None) -> str:
    """Gather what is left to use, for the ring and its centre label.

    ns.cards  [dollars, card_id, colour] per active card with money left
    ns.rems   [dollars, card_id] per benefit with money left
    ns.total  the sum of those benefits
    """
    scope = f" and {ONLY_CARD.format(card_id=card_id)}" if card_id else ""
    return (
        "{% set ns = namespace(total=0.0, cards=[], rems=[], acc=0.0, out=[]) %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'unused_value' "
        f"and {ONLY_ACTIVE}{scope} "
        "and s.state not in ['unknown', 'unavailable'] and (s.state | float(0)) > 0 %}"
        "{% set ns.cards = ns.cards + [[s.state | float(0), s.attributes.get('card_id'), "
        "s.attributes.get('color') or 'grey']] %}"
        "{% endfor %}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'benefit_remaining' "
        f"and {ONLY_ACTIVE}{scope} "
        "and s.state not in ['unknown', 'unavailable'] and (s.state | float(0)) > 0 %}"
        "{% set ns.rems = ns.rems + [[s.state | float(0), s.attributes.get('card_id')]] %}"
        "{% set ns.total = ns.total + (s.state | float(0)) %}"
        "{% endfor %}"
    )


def donut_by_card(size: int = 240, *, card_id: str | None = None) -> dict:
    """One ring of the dollars left to use: a slice per card, subdivided by benefit.

    Cards run largest first; within a card each benefit is a segment, largest first,
    in a shade of the card's colour that steps from full strength down to about half,
    mixed towards the card background so it works in either theme. Scoped to one
    card, the ring is that card's credits alone.

    A Markdown card: card-mod paints its inner markdown element as a conic gradient
    computed by a template, lays a disc of card background over the centre, and the
    card's own content prints the total in the middle. The size is forced because the
    card frame itself takes Home Assistant's sizing. Shades use CSS color-mix, which
    every current browser supports.
    """
    gather = _left_to_use(card_id)
    slices = (
        gather + "{% for c in ns.cards | sort(attribute='0', reverse=true) %}"
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
        "  display: flex !important; align-items: center; justify-content: center;\n"
        "}\n"
        "ha-markdown {\n"
        f"  width: {size}px !important; height: {size}px !important; border-radius: 50%;\n"
        "  margin: auto !important; padding: 0 !important; box-sizing: border-box;\n"
        "  display: flex !important; align-items: center; justify-content: center;\n"
        "  text-align: center; font-size: 1.15em; line-height: 1.5;\n"
        "  background:\n"
        "    radial-gradient(circle closest-side, "
        "var(--ha-card-background, var(--card-background-color)) 70%, transparent 71%),\n"
        "    conic-gradient(" + slices + ");\n"
        "}\n"
    )
    if card_id:
        label = (
            "**${{ ns.total | round(0) | int }}**<br>left to use<br>"
            "{{ ns.rems | count }} credit{{ '' if ns.rems | count == 1 else 's' }}"
        )
    else:
        label = (
            "**${{ ns.total | round(0) | int }}**<br>left to use<br>"
            "{{ ns.rems | count }} credits on {{ ns.cards | count }} card"
            "{{ '' if ns.cards | count == 1 else 's' }}"
        )
    return {"type": "markdown", "content": gather + label, "card_mod": {"style": style}}


def money_bars(*, card_id: str | None = None, with_name: bool = True) -> dict:
    """A stacked bar per card: where the trailing year's credit dollars went.

    One scheme for every card so the bars read the same everywhere: green captured,
    red forfeited, grey unknown (months with no statement), and a dim track for what
    is still open to capture, like a progress bar. The CardPerks theme supplies the
    three colours (`--cardperks-captured` and friends); without it HA's palette is used. Card colours stay on the rings and
    gauges. Built by a template over the capture-rate sensors, so cards come and go by
    themselves.
    """
    scope = f" and {ONLY_CARD.format(card_id=card_id)}" if card_id else ""
    bar_css = 'content: ""; display: block; height: 12px; border-radius: 6px; margin: 2px 0 10px;'
    bar = (
        "'ha-markdown::before { " + bar_css + " background: linear-gradient(to right, "
        "var(--cardperks-captured, var(--green-color)) 0% ' ~ a ~ '%, "
        "var(--cardperks-forfeited, var(--red-color)) ' ~ a ~ '% ' ~ b ~ '%, "
        "var(--cardperks-unknown, var(--grey-color)) ' ~ b ~ '% ' ~ c ~ '%, "
        "var(--divider-color) ' ~ c ~ '% 100%); }'"
    )
    empty = "'ha-markdown::before { " + bar_css + " background: var(--divider-color); }'"
    head = (
        "'**' ~ s.attributes.get('card') ~ '** · ' ~ (s.state | float(0) | round(0) | int) "
        "~ '% captured<br>'"
        if with_name
        else "'**' ~ (s.state | float(0) | round(0) | int) ~ '% captured**<br>'"
    )
    template = (
        "{% set ns = namespace(cards=[]) %}"
        "{% for s in states.sensor if s.state not in ['unavailable', 'unknown'] "
        f"and s.attributes.get('kind') == 'capture_rate' and {ONLY_ACTIVE}{scope} %}}"
        "{% set cap = s.attributes.get('captured_12m') or 0 %}"
        "{% set forf = s.attributes.get('forfeited_12m') or 0 %}"
        "{% set unk = s.attributes.get('unknown_12m') or 0 %}"
        "{% set open = s.attributes.get('open_remaining') or 0 %}"
        "{% set tot = cap + forf + unk + open %}"
        "{% if tot > 0 %}"
        "{% set a = (cap / tot * 100) | round(2) %}"
        "{% set b = ((cap + forf) / tot * 100) | round(2) %}"
        "{% set c = ((cap + forf + unk) / tot * 100) | round(2) %}"
        "{% set style = " + bar + " %}"
        "{% else %}{% set style = " + empty + " %}{% endif %}"
        "{% set text = " + head + " ~ '$' ~ (cap | round(0) | int) ~ ' captured · $' "
        "~ (forf | round(0) | int) ~ ' forfeited · $' ~ (unk | round(0) | int) "
        "~ ' unknown · $' ~ (open | round(0) | int) ~ ' still open' %}"
        "{% set ns.cards = ns.cards + [{'type': 'markdown', 'content': text, "
        "'card_mod': {'style': style}, 'sort': s.attributes.get('card')}] %}"
        "{% endfor %}"
        "{{ ns.cards | sort(attribute='sort') }}"
    )
    return _template_cards(template)


def _money_gather(min_amount: float) -> str:
    """Jinja that totals the trailing year for credits worth at least `min_amount` a period."""
    return (
        "{% set ns = namespace(cap=0.0, forf=0.0, unk=0.0, open=0.0, n=0) %}"
        "{% for s in states.number if s.attributes.get('kind') == 'benefit_used' "
        f"and {ONLY_ACTIVE} and (s.attributes.get('this_period') or 0) >= {min_amount} %}}"
        "{% set ns.cap = ns.cap + (s.attributes.get('captured_12m') or 0) %}"
        "{% set ns.forf = ns.forf + (s.attributes.get('forfeited_12m') or 0) %}"
        "{% set ns.unk = ns.unk + (s.attributes.get('unknown_12m') or 0) %}"
        "{% set ns.open = ns.open + (s.attributes.get('open_remaining') or 0) %}"
        "{% set ns.n = ns.n + 1 %}"
        "{% endfor %}"
        "{% set tot = ns.cap + ns.forf + ns.unk + ns.open %}"
    )


def money_legend(*, min_amount: float) -> dict:
    """The line under the ring: the four figures, in the ring's own words."""
    return note(
        _money_gather(min_amount) + "**${{ ns.cap | round(0) | int }}** captured · "
        "**${{ ns.forf | round(0) | int }}** forfeited · "
        "**${{ ns.unk | round(0) | int }}** unknown · "
        "**${{ ns.open | round(0) | int }}** still open"
    )


def money_donut(*, min_amount: float, size: int = 240, title: str = "big-ticket credits") -> dict:
    """One ring of where the trailing year's dollars went for credits worth at least
    `min_amount` a period: captured, forfeited, unknown, still open, in the same scheme
    as the money bars. The centre prints what was missed. Reads the per-benefit totals
    every dollar box carries, so it needs nothing beyond the entities."""
    gather = _money_gather(min_amount)
    slices = (
        gather + "{% if tot > 0 %}"
        "{% set a = (ns.cap / tot * 100) | round(2) %}"
        "{% set b = ((ns.cap + ns.forf) / tot * 100) | round(2) %}"
        "{% set c = ((ns.cap + ns.forf + ns.unk) / tot * 100) | round(2) %}"
        "var(--cardperks-captured, var(--green-color)) 0% {{ a }}%, "
        "var(--cardperks-forfeited, var(--red-color)) {{ a }}% {{ b }}%, "
        "var(--cardperks-unknown, var(--grey-color)) {{ b }}% {{ c }}%, "
        "var(--divider-color) {{ c }}% 100%"
        "{% else %}var(--divider-color) 0% 100%{% endif %}"
    )
    style = "\n".join(
        [
            "ha-card {",
            "  display: flex !important; align-items: center; justify-content: center;",
            "}",
            "ha-markdown {",
            f"  width: {size}px !important; height: {size}px !important; border-radius: 50%;",
            "  margin: auto !important; padding: 0 !important; box-sizing: border-box;",
            "  display: flex !important; align-items: center; justify-content: center;",
            "  text-align: center; font-size: 1.05em; line-height: 1.5;",
            "  background:",
            "    radial-gradient(circle closest-side, "
            "var(--ha-card-background, var(--card-background-color)) 70%, transparent 71%),",
            "    conic-gradient(" + slices + ");",
            "}",
        ]
    )
    label = (
        gather + "**${{ ns.forf | round(0) | int }}** missed<br>"
        "<span style='color: var(--secondary-text-color)'>of ${{ tot | round(0) | int }}<br>"
        "{{ ns.n }} " + title + "</span>"
    )
    return {"type": "markdown", "content": label, "card_mod": {"style": style}}


def missed_list(*, min_amount: float) -> dict:
    """The big credits that were forfeited over the trailing year, largest loss first."""
    return auto_cards(
        [
            {
                "attributes": {
                    "kind": "benefit_used",
                    "card_status": "active",
                    "this_period": f">= {min_amount}",
                    "forfeited_12m": "> 0",
                },
                "domain": "number",
            }
        ],
        primary="${{ (state_attr(entity, 'forfeited_12m') or 0) | round(0) | int }} missed · "
        "{{ state_attr(entity, 'benefit') }}",
        secondary="{{ state_attr(entity, 'card') }} · "
        "${{ (state_attr(entity, 'captured_12m') or 0) | round(0) | int }} captured this year",
        icon="mdi:close-circle-outline",
        sort={
            "method": "attribute",
            "attribute": "forfeited_12m",
            "numeric": True,
            "reverse": True,
        },
    )


# ------------------------------------------------------------------ credits by period

OUTCOME_COLORS = {
    "captured": "var(--cardperks-captured, var(--green-color))",
    "partial": "var(--cardperks-partial, var(--amber-color))",
    "forfeited": "var(--cardperks-forfeited, var(--red-color))",
    "unknown": "var(--cardperks-unknown, var(--grey-color))",
    "open": "var(--cardperks-open, var(--blue-grey-color))",
    "future": "var(--divider-color)",
    "na": "var(--divider-color)",
}


def period_rings(card_id: str | None = None, *, size: int = 118, columns: int = 4) -> dict:
    """One small ring per benefit: a slice per period this year, coloured by outcome.

    Every benefit status sensor carries `periods`, a list the coordinator builds, so
    this is one short template for any card and any cadence: twelve slices for a
    monthly credit, two for a half-yearly one, one for a yearly. Green captured, amber
    partial, red forfeited, grey unknown, blue-grey in progress, dim for periods still
    to come. The centre counts captured periods over the periods that have started;
    the card title names the benefit. A past period with nothing recorded is forfeited.
    """
    colours = "{" + ", ".join(f"'{k}': '{v}'" for k, v in OUTCOME_COLORS.items()) + "}"
    where = f"s.attributes.get('card_id') == '{card_id}' and " if card_id else ""
    style = (
        "ha-card { padding: 0 0 8px; }"
        " .card-header { font-size: 12.5px; line-height: 1.25; padding: 8px 8px 6px; "
        "text-align: center; min-height: 0; }"
        f" ha-markdown {{ width: {size}px !important; height: {size}px !important; "
        "border-radius: 50%; margin: 0 auto !important; padding: 0 !important; "
        "box-sizing: border-box; display: flex !important; align-items: center; "
        "justify-content: center; text-align: center; font-size: 1em; line-height: 1.3; "
        "background: radial-gradient(circle closest-side, "
        "var(--ha-card-background, var(--card-background-color)) 66%, transparent 67%), "
        "conic-gradient(' ~ (seg.out | join(', ')) ~ '); }"
    )
    template = (
        "{% set ns = namespace(cards=[]) %}"
        f"{{% set colours = {colours} %}}"
        "{% for s in states.sensor if s.attributes.get('kind') == 'benefit_status' "
        f"and {where}{ONLY_ACTIVE} and (s.attributes.get('periods') or []) | count > 0 %}}"
        "{% set ps = s.attributes.get('periods') %}{% set n = ps | count %}"
        "{% set gap = 0.7 if n > 1 else 0 %}"
        "{% set seg = namespace(out=[], got=0, done=0) %}"
        "{% for p in ps %}"
        "{% set c = colours.get(p.outcome, 'var(--divider-color)') %}"
        "{% set a = loop.index0 * 100 / n %}{% set b = loop.index * 100 / n %}"
        "{% set seg.out = seg.out + [c ~ ' ' ~ ((a + gap) | round(2)) ~ '% ' ~ ((b - gap) | round(2)) ~ '%'] %}"
        "{% if gap %}{% set seg.out = seg.out + ['var(--ha-card-background, var(--card-background-color)) ' "
        "~ ((b - gap) | round(2)) ~ '% ' ~ ((b + gap) | round(2)) ~ '%'] %}{% endif %}"
        "{% if p.outcome == 'captured' %}{% set seg.got = seg.got + 1 %}{% endif %}"
        "{% if p.outcome != 'future' %}{% set seg.done = seg.done + 1 %}{% endif %}"
        "{% endfor %}"
        "{% set ns.cards = ns.cards + [{'type': 'markdown', "
        "'title': s.attributes.get('benefit'), "
        "'content': '**' ~ seg.got ~ '/' ~ n ~ '**<br><span style=\"font-size: 0.8em; "
        "color: var(--secondary-text-color)\">of ' ~ seg.done ~ ' so far</span>', "
        f"'card_mod': {{'style': '{style}'}}, "
        "'sort': (0 if ps[0].outcome else 1) ~ s.attributes.get('benefit')}] %}"
        "{% endfor %}"
        "{{ ns.cards | sort(attribute='sort') }}"
    )
    return _template_cards(template, columns=columns, show_empty=True)
