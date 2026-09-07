"""Render the catalog as one readable HTML page. Pure: takes a Catalog, returns a string.

Served live by the sidebar panel, so overrides and reloads show up at once. Carries
only catalog data, never anything about held cards, which is why it can be served
without a login (see panel.py).
"""

from __future__ import annotations

import html
import json
from datetime import date

from .const import AppliesTo, BenefitType, Cadence, ResetRule, SpendCategory
from .models import Benefit, Catalog

CADENCE_WORDS = {
    Cadence.MONTHLY: "monthly",
    Cadence.QUARTERLY: "quarterly",
    Cadence.SEMIANNUAL: "every 6 months",
    Cadence.ANNUAL: "yearly",
    Cadence.PER_ANNIVERSARY: "each anniversary",
    Cadence.EVERY_FOUR_YEARS: "every 4 years",
    Cadence.ONE_TIME: "one-time",
}
CATEGORY_WORDS = {
    SpendCategory.DINING: "Dining",
    SpendCategory.GROCERIES: "Groceries",
    SpendCategory.GAS: "Gas and EV charging",
    SpendCategory.FLIGHTS: "Flights, booked with the airline",
    SpendCategory.HOTELS: "Hotels, booked with the hotel",
    SpendCategory.CAR_RENTAL: "Car rental",
    SpendCategory.TRAVEL: "Other travel",
    SpendCategory.ISSUER_TRAVEL_PORTAL: "Travel booked through the issuer's portal",
    SpendCategory.BRAND_AIRLINE: "The card's own airline",
    SpendCategory.TRANSIT: "Transit, rideshare, tolls, parking",
    SpendCategory.STREAMING: "Streaming",
    SpendCategory.WIRELESS: "Wireless phone service",
    SpendCategory.INTERNET_CABLE_PHONE: "Internet, cable and phone",
    SpendCategory.SHIPPING: "Shipping",
    SpendCategory.ADVERTISING: "Advertising",
    SpendCategory.ELECTRONICS_SOFTWARE: "Electronics, software and cloud",
    SpendCategory.ENTERTAINMENT: "Event tickets through the issuer",
    SpendCategory.LARGE_PURCHASE: "Single purchases of $5,000 or more",
    SpendCategory.OTHER: "Everything else",
}
TYPE_WORDS = {
    BenefitType.STATEMENT_CREDIT: "credit",
    BenefitType.PERK: "perk",
    BenefitType.INSURANCE: "insurance",
    BenefitType.REBATE: "rebate",
    BenefitType.EARNING: "points",
}


def _esc(s: object) -> str:
    return html.escape(str(s)) if s is not None else ""


def _money(v: float | None) -> str:
    if v is None:
        return ""
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600"
    "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
)


def _my_default(
    product_id: str, b: Benefit, per_year: float, my_values: dict[str, dict[str, float]]
) -> str:
    """What the My-value box starts at: the household's own figure for a perk on a card
    it holds, else the catalog's yearly amount for a credit, else zero."""
    mine = my_values.get(product_id, {}).get(b.id)
    if mine is not None:
        return f"{mine:g}"
    if b.type is BenefitType.STATEMENT_CREDIT and per_year:
        return f"{per_year:g}"
    return "0"


def render_catalog(
    catalog: Catalog,
    *,
    source_note: str = "",
    fonts_href: str = "/cardperks/static/fonts.css",
    owned: frozenset[str] = frozenset(),
    my_values: dict[str, dict[str, float]] | None = None,
) -> str:
    """The whole catalog as an HTML document (title and styles included).

    `owned` is the set of product ids the household holds: those products are marked,
    and the page opens showing only them, with a toggle for the rest. `my_values` is
    {product id: {benefit id: dollars a year}}: what the household already values a
    perk at, used to prefill the "My value" column; the page keeps edits in the browser.
    """
    my_values = my_values or {}
    by_issuer = catalog.by_issuer()
    issuer_names = catalog.issuers()
    today = date.today().isoformat()

    nav: list[str] = []
    sections: list[str] = []
    lookup: list[dict] = []
    total_products = 0
    flagged = 0
    overridden = 0
    for issuer in sorted(by_issuer, key=lambda i: issuer_names[i]):
        nav.append(f'<li class="nav-issuer">{_esc(issuer_names[issuer])}</li>')
        for p in by_issuer[issuer]:
            total_products += 1
            flagged += p.needs_verification
            overridden += p.origin != "shipped"
            held = p.id in owned
            lookup.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "issuer": p.issuer_name,
                    "held": held,
                    "currency": p.currency_name,
                    "cents": round(p.default_point_value * 100, 2),
                    "rates": [
                        {"c": str(r.category), "x": r.multiplier, "n": r.notes or ""}
                        for r in p.earning_rates
                    ],
                }
            )
            nav.append(
                f'<li class="{"held" if held else "not-held"}"><a href="#{_esc(p.id)}">'
                f"{_esc(p.name)}</a></li>"
            )
            rows: list[str] = []
            annual = 0.0
            for b in p.benefits:
                per_year = (
                    b.annual_value() if b.is_dollar and b.type is not BenefitType.REBATE else 0.0
                )
                annual += per_year
                amount = ""
                if b.type is BenefitType.EARNING:
                    amount = f"{b.amount:,.0f} {b.unit}" if b.amount else ""
                elif b.amount is not None:
                    amount = _money(b.amount)
                elif b.default_value:
                    amount = f'{_money(b.default_value)} <span class="muted">your value</span>'
                cadence = CADENCE_WORDS[b.cadence]
                if (
                    b.cadence in (Cadence.ANNUAL, Cadence.PER_ANNIVERSARY)
                    and b.reset is ResetRule.CARDMEMBER_YEAR
                ):
                    cadence = "each anniversary year"
                elif b.cadence is Cadence.ANNUAL:
                    cadence = "each calendar year"
                match = ", ".join(f"<code>{_esc(m)}</code>" for m in b.statement_match)
                flags: list[str] = []
                if b.conditional:
                    flags.append(
                        f'<span class="chip chip-cond" title="{_esc(b.condition or "")}">'
                        "if you qualify</span>"
                    )
                if b.enrollment_required:
                    flags.append('<span class="chip">enroll</span>')
                if b.applies_to.value != "primary":
                    flags.append('<span class="chip">AU too</span>')
                if b.shared_key:
                    flags.append(
                        f'<span class="chip" title="Valued once for the household as '
                        f'{_esc(b.shared_key)} and split between the cards that carry it">'
                        "shared</span>"
                    )
                rows.append(
                    "<tr>"
                    f'<td class="b-name"><div class="b-title">{_esc(b.name)} {" ".join(flags)}</div>'
                    f'<div class="b-notes">{_esc(b.notes or "")}</div>'
                    + (
                        f'<div class="eligible">Eligible: {_esc(", ".join(b.eligible))}</div>'
                        if b.eligible
                        else ""
                    )
                    + "</td>"
                    f'<td><span class="type type-{b.type.value}">{TYPE_WORDS[b.type]}</span></td>'
                    f'<td class="num">{amount}</td>'
                    f"<td>{_esc(cadence)}</td>"
                    f'<td class="num">{_money(per_year) if per_year else ""}</td>'
                    f'<td class="num"><input class="my" type="text" inputmode="decimal" '
                    f'data-p="{_esc(p.id)}" data-b="{_esc(b.id)}" '
                    f'data-default="{_my_default(p.id, b, per_year, my_values)}" '
                    f'value="{_my_default(p.id, b, per_year, my_values)}" '
                    f'aria-label="My value per year for {_esc(b.name)}"></td>'
                    f'<td class="match">{match}</td>'
                    "</tr>"
                )
            au = p.au_terms
            au_text = f"Additional card {_money(au.fee)}" if au.fee else "Additional cards free"
            if au.notes:
                au_text += f". {au.notes}"
            earns = " · ".join(
                f'<span title="{_esc(r.notes or "")}">{r.multiplier:g}&times; '
                f"{_esc(CATEGORY_WORDS[r.category].lower())}</span>"
                for r in sorted(p.earning_rates, key=lambda r: -r.multiplier)
            )
            earns_line = (
                f'<p class="p-earns">Earns {_esc(p.currency_name)}: {earns}.</p>' if earns else ""
            )
            chips = ""
            if held:
                chips += '<span class="chip chip-held">you hold this</span>'
            if p.needs_verification:
                chips += '<span class="chip chip-flag">needs verification</span>'
            if p.origin != "shipped":
                chips += f'<span class="chip chip-over" title="{_esc(p.origin)}">override</span>'
            sections.append(
                f'<section class="product {"held" if held else "not-held"}" id="{_esc(p.id)}" '
                f'data-fee="{p.annual_fee}">'
                '<header class="p-head">'
                f'<div><p class="eyebrow">{_esc(p.issuer_name)}</p>'
                f"<h2>{_esc(p.name)} {chips}</h2>"
                f'<p class="p-meta">{_esc(au_text)}. Checked {_esc(p.last_verified.isoformat())} '
                f'against <a href="{_esc(p.source_url)}" target="_blank" rel="noopener">the issuer '
                f"page</a>. Catalog id <code>{_esc(p.id)}</code>.</p>{earns_line}</div>"
                '<dl class="p-figures">'
                f"<div><dt>Annual fee</dt><dd>{_money(p.annual_fee)}</dd></div>"
                f"<div><dt>Credits per year</dt><dd>{_money(annual)}</dd></div>"
                '<div class="mine"><dt>My credits per year</dt><dd data-my-credits>$0</dd></div>'
                '<div class="mine"><dt>My net per year</dt><dd data-my-net>$0</dd></div>'
                f"<div><dt>Benefits</dt><dd>{len(p.benefits)}</dd></div></dl>"
                "</header>"
                '<div class="table-wrap"><table>'
                '<thead><tr><th>Benefit</th><th>Type</th><th class="num">Per period</th>'
                '<th>Cadence</th><th class="num">Per year</th>'
                '<th class="num">My value / yr <a href="#" class="reset" title="Back to the defaults">reset</a></th>'
                "<th>Statement match</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div>"
                "</section>"
            )

    programs = sorted(catalog.programs.values(), key=lambda p: p.name)
    if programs:
        nav.append('<li class="nav-issuer">Loyalty programs</li>')
    for pr in programs:
        nav.append(f'<li><a href="#program-{_esc(pr.id)}">{_esc(pr.name)}</a></li>')
        rows = []
        for t in sorted(pr.tiers, key=lambda t: t.rank):
            rows.append(
                "<tr>"
                f'<td class="b-name"><div class="b-title">{_esc(t.name)}</div></td>'
                f"<td>{_esc(t.qualify)}</td>"
                f'<td><ul class="tier-benefits">'
                + "".join(f"<li>{_esc(b)}</li>" for b in t.benefits)
                + "</ul></td></tr>"
            )
        sections.append(
            f'<section class="product program" id="program-{_esc(pr.id)}">'
            '<header class="p-head">'
            f'<div><p class="eyebrow">Loyalty program · {_esc(pr.kind)}</p>'
            f"<h2>{_esc(pr.name)}</h2>"
            f'<p class="p-meta">{_esc(pr.qualification)} Checked {_esc(pr.last_verified.isoformat())} '
            f'against <a href="{_esc(pr.source_url)}" target="_blank" rel="noopener">the program page</a>. '
            f"Catalog id <code>{_esc(pr.id)}</code>.</p></div>"
            '<dl class="p-figures">'
            f"<div><dt>{_esc(pr.tier_word)} tiers</dt><dd>{len(pr.tiers)}</dd></div></dl>"
            "</header>"
            '<div class="table-wrap"><table>'
            "<thead><tr><th>Tier</th><th>How to qualify</th><th>What it gives</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div></section>"
        )

    category_options = "".join(
        f'<option value="{_esc(c)}"{" selected" if c is SpendCategory.DINING else ""}>'
        f"{_esc(CATEGORY_WORDS[c])}</option>"
        for c in SpendCategory
    )
    currencies = sorted({(d["currency"], d["cents"]) for d in lookup})
    cents_inputs = "".join(
        f'<label><span>{_esc(name)}</span><input class="cents" type="text" inputmode="decimal" '
        f'data-currency="{_esc(name)}" data-default="{cents:g}" value="{cents:g}" '
        f'aria-label="Cents per point for {_esc(name)}">¢</label>'
        for name, cents in currencies
    )
    best_card = (
        '<section class="product lookup" id="best-card">'
        '<header class="p-head"><div><p class="eyebrow">Before you pay</p>'
        "<h2>Best card for this purchase</h2>"
        '<p class="p-meta">Pick where the money is going and the cards rank by what they earn '
        "there, from each issuer's own page. Points and miles are not worth the same, so the "
        "ranking uses your cents-per-point figures below; they start at one cent and stay in "
        "this browser. Hover a rate for the issuer's fine print (caps, portal-only, promo dates)."
        "</p></div></header>"
        '<div class="lookup-body">'
        '<label class="lookup-pick">Spending on '
        f'<select id="lookup-category" aria-label="Spend category">{category_options}</select></label>'
        '<ol class="ranking" id="lookup-ranking"></ol>'
        f'<div class="cents-row"><span class="cents-title">Cents per point</span>{cents_inputs}'
        '<a href="#" class="reset" id="cents-reset">reset</a></div>'
        "</div></section>"
    )
    sections.insert(0, best_card)

    # Adding an authorized user: what it costs and what the second card actually gets.
    au_rows = []
    for p in sorted(
        catalog.products.values(), key=lambda p: (p.id not in owned, p.issuer_name, p.name)
    ):
        held = p.id in owned
        gets = [
            b.name + (" (own allotment)" if b.applies_to is AppliesTo.AU_OWN_ALLOTMENT else "")
            for b in p.benefits
            if b.applies_to is not AppliesTo.PRIMARY
        ]
        au_rows.append(
            f'<tr class="{"held" if held else "not-held"}">'
            f'<td class="b-name"><div class="b-title"><a href="#{_esc(p.id)}">{_esc(p.name)}</a>'
            f"{' <span class="chip chip-held">held</span>' if held else ''}</div>"
            f'<div class="b-notes">{_esc(p.issuer_name)}</div></td>'
            f'<td class="num">{_money(p.au_terms.fee) if p.au_terms.fee else "Free"}</td>'
            f"<td>{'Yes' if p.au_terms.own_lounge_access else 'No'}</td>"
            f"<td>{_esc('; '.join(gets)) if gets else '<span class="muted">Nothing of its own listed</span>'}</td>"
            f'<td class="b-notes">{_esc(p.au_terms.notes or "")}</td>'
            "</tr>"
        )
    au_section = (
        '<section class="product lookup" id="authorized-users">'
        '<header class="p-head"><div><p class="eyebrow">Before you add someone</p>'
        "<h2>Adding an authorized user</h2>"
        '<p class="p-meta">What a second card costs and what it gets in its own right, from '
        "each issuer's page. Statement credits are almost never doubled; lounge access and "
        "elite status sometimes are. Cards you hold come first.</p></div></header>"
        '<div class="table-wrap"><table>'
        '<thead><tr><th>Card</th><th class="num">AU fee</th><th>Own lounge access</th>'
        "<th>The authorized user gets</th><th>Notes</th></tr></thead>"
        f"<tbody>{''.join(au_rows)}</tbody></table></div></section>"
    )
    sections.insert(1, au_section)
    lookup_json = json.dumps(lookup).replace("</", "<\\/")

    summary = f"{total_products} products"
    if programs:
        summary += f", {len(programs)} loyalty program{'s' if len(programs) != 1 else ''}"
    if owned:
        summary += f", {len(owned)} held"
    if flagged:
        summary += f", {flagged} still to verify"
    if overridden:
        summary += f", {overridden} overridden in config/cardperks/catalog/"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CardPerks Catalog</title>
<link rel="stylesheet" href="{_esc(fonts_href)}">
<style>
:root {{
  --paper: #f5f6f8; --panel: #ffffff; --ink: #1c2027; --ink-2: #4f5866; --ink-3: #7d8697;
  --rule: #dde1e7; --brass: #a9781f; --brass-soft: #f4ecd8; --flag: #b45309; --flag-soft: #fdf0dc;
  --credit: #1d6b4e; --credit-soft: #e2f2ea; --perk: #4a5b8c; --perk-soft: #e6eaf6;
  --code: #eef0f3;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper: #14171c; --panel: #1b1f26; --ink: #e8eaee; --ink-2: #aab2bf; --ink-3: #7f8896;
    --rule: #2b313b; --brass: #d3a33f; --brass-soft: #2e2818; --flag: #f0a640; --flag-soft: #33271a;
    --credit: #6fcf9a; --credit-soft: #17302a; --perk: #9fb0e0; --perk-soft: #222a3d;
    --code: #262c36;
  }}
}}
:root[data-theme="dark"] {{
  --paper: #14171c; --panel: #1b1f26; --ink: #e8eaee; --ink-2: #aab2bf; --ink-3: #7f8896;
  --rule: #2b313b; --brass: #d3a33f; --brass-soft: #2e2818; --flag: #f0a640; --flag-soft: #33271a;
  --credit: #6fcf9a; --credit-soft: #17302a; --perk: #9fb0e0; --perk-soft: #222a3d;
  --code: #262c36;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.5 "IBM Plex Sans", "Segoe UI", system-ui, sans-serif; }}
a {{ color: var(--brass); }}
a:focus-visible, input:focus-visible {{ outline: 2px solid var(--brass); outline-offset: 2px; }}
code {{ font: 12.5px/1.4 "IBM Plex Mono", Consolas, monospace; background: var(--code); padding: 1px 5px; border-radius: 3px; }}
.page {{ display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 40px; max-width: 1180px; margin: 0 auto; padding: 36px 28px 80px; }}
.side {{ position: sticky; top: 24px; align-self: start; }}
.side h1 {{ font: 600 30px/1.05 "Newsreader", Georgia, serif; margin: 0 0 6px; letter-spacing: -0.01em; }}
.side .sub {{ color: var(--ink-2); margin: 0 0 18px; font-size: 13.5px; }}
.side input {{ width: 100%; padding: 8px 10px; border: 1px solid var(--rule); border-radius: 6px; background: var(--panel); color: var(--ink); font: inherit; margin-bottom: 14px; }}
.side ul {{ list-style: none; margin: 0; padding: 0; }}
.side li a {{ display: block; padding: 4px 0 4px 10px; color: var(--ink-2); text-decoration: none; border-left: 2px solid transparent; }}
.side li a:hover {{ color: var(--ink); border-left-color: var(--brass); }}
.nav-issuer {{ font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); margin: 14px 0 4px; }}
.main {{ display: grid; gap: 28px; min-width: 0; }}
.intro {{ max-width: 62ch; color: var(--ink-2); margin: 0; }}
.product {{ background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 22px 24px 8px; }}
.p-head {{ display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; flex-wrap: wrap; padding-bottom: 14px; border-bottom: 1px solid var(--rule); margin-bottom: 4px; }}
.eyebrow {{ margin: 0 0 2px; font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }}
h2 {{ font: 600 26px/1.1 "Newsreader", Georgia, serif; margin: 0 0 6px; text-wrap: balance; }}
.p-meta {{ margin: 0; color: var(--ink-2); font-size: 13.5px; max-width: 64ch; }}
.p-figures {{ display: flex; gap: 26px; margin: 0; }}
.p-figures div {{ display: grid; gap: 2px; }}
.p-figures dt {{ font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }}
.p-figures dd {{ margin: 0; font: 500 24px/1.1 "Newsreader", Georgia, serif; font-variant-numeric: tabular-nums; }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{ text-align: left; font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); font-weight: 500; padding: 10px 10px 8px 0; border-bottom: 1px solid var(--rule); }}
td {{ padding: 10px 10px 10px 0; border-bottom: 1px solid var(--rule); vertical-align: top; }}
tr:last-child td {{ border-bottom: 0; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
th.num {{ text-align: right; }}
.b-name {{ min-width: 260px; }}
.b-title {{ font-weight: 500; }}
.b-notes {{ color: var(--ink-2); font-size: 13px; max-width: 58ch; }}
.eligible {{ margin: 4px 0 0; color: var(--ink-3); font-size: 12.5px; max-width: 58ch; }}
.tier-benefits {{ margin: 0; padding-left: 16px; font-size: 13px; color: var(--ink-2); }}
.tier-benefits li {{ margin: 2px 0; }}
.match {{ min-width: 160px; }}
.match code {{ margin-right: 4px; }}
.type {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; white-space: nowrap; }}
.type-statement_credit, .type-rebate {{ background: var(--credit-soft); color: var(--credit); }}
.type-perk, .type-insurance {{ background: var(--perk-soft); color: var(--perk); }}
.type-earning {{ background: var(--code); color: var(--ink-2); }}
.chip {{ display: inline-block; padding: 0 7px; border-radius: 999px; font-size: 11.5px; background: var(--code); color: var(--ink-2); vertical-align: 2px; }}
.chip-cond {{ background: var(--brass-soft); color: var(--brass); }}
.chip-flag, .chip-over {{ font: 500 12px/1.6 "IBM Plex Sans", sans-serif; vertical-align: middle; margin-left: 6px; }}
.chip-flag {{ background: var(--flag-soft); color: var(--flag); }}
.chip-held {{ background: var(--credit-soft); color: var(--credit); font: 500 12px/1.6 "IBM Plex Sans", sans-serif; vertical-align: middle; margin-left: 6px; }}
.toggle {{ display: flex; align-items: center; gap: 8px; margin: 0 0 14px; font-size: 13.5px; color: var(--ink-2); cursor: pointer; }}
.toggle input {{ width: auto; margin: 0; accent-color: var(--brass); }}
body.only-held .not-held {{ display: none; }}
body.only-held .program {{ display: block; }}
.chip-over {{ background: var(--brass-soft); color: var(--brass); }}
.muted {{ color: var(--ink-3); font-size: 12px; }}
input.my {{ width: 76px; padding: 4px 6px; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); color: var(--ink); font: 13.5px "IBM Plex Sans", sans-serif; text-align: right; font-variant-numeric: tabular-nums; }}
input.my:focus {{ outline: 2px solid var(--brass); outline-offset: 1px; }}
input.my::-webkit-outer-spin-button, input.my::-webkit-inner-spin-button {{ -webkit-appearance: none; margin: 0; }}
th .reset {{ font-weight: 400; text-transform: none; letter-spacing: 0; margin-left: 6px; font-size: 11px; }}
.p-figures .mine dd {{ color: var(--brass); }}
.p-figures .mine dd.negative {{ color: var(--flag); }}
.hidden {{ display: none; }}
.p-earns {{ margin: 6px 0 0; color: var(--ink-2); font-size: 13px; max-width: 72ch; }}
.p-earns span {{ white-space: nowrap; }}
.lookup {{ border-color: var(--brass); }}
.lookup-body {{ display: grid; gap: 14px; padding: 14px 0 12px; }}
.lookup-pick {{ font-size: 14px; color: var(--ink-2); }}
.lookup-pick select {{ margin-left: 6px; padding: 6px 8px; border: 1px solid var(--rule); border-radius: 6px; background: var(--panel); color: var(--ink); font: inherit; max-width: 100%; }}
.ranking {{ margin: 0; padding-left: 0; list-style: none; display: grid; gap: 6px; }}
.ranking li {{ display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 10px; align-items: baseline; padding: 6px 0; border-bottom: 1px solid var(--rule); }}
.ranking li:last-child {{ border-bottom: 0; }}
.ranking .rank {{ font: 500 18px/1 "Newsreader", Georgia, serif; color: var(--ink-3); }}
.ranking li.top .rank {{ color: var(--brass); }}
.ranking .who {{ min-width: 0; }}
.ranking .who small {{ display: block; color: var(--ink-3); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.ranking .rate {{ font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }}
.ranking .rate small {{ display: block; color: var(--ink-3); font-size: 12px; }}
.ranking li.not-held {{ display: none; }}
body:not(.only-held) .ranking li.not-held {{ display: grid; opacity: 0.6; }}
.ranking .empty {{ color: var(--ink-3); font-size: 13.5px; display: block; }}
.cents-row {{ display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; font-size: 13px; color: var(--ink-2); }}
.cents-title {{ font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }}
.cents-row label {{ display: inline-flex; gap: 6px; align-items: center; }}
.cents-row input.cents {{ width: 52px; padding: 3px 5px; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); color: var(--ink); font: 13px "IBM Plex Sans", sans-serif; text-align: right; }}
.cents-row .reset {{ font-size: 11px; }}
@media (max-width: 820px) {{ .page {{ grid-template-columns: 1fr; gap: 20px; }} .side {{ position: static; }} .p-figures {{ gap: 18px; }} }}
@media (prefers-reduced-motion: no-preference) {{ html {{ scroll-behavior: smooth; }} }}
</style></head><body>
<script id="cp-data" type="application/json">{lookup_json}</script>
<div class="page">
  <aside class="side">
    <h1>CardPerks Catalog</h1>
    <p class="sub">{_esc(summary)}. {_esc(source_note) or f"Rendered {today}."}</p>
    <input type="search" id="q" placeholder="Filter benefits…" aria-label="Filter benefits">
    {'<label class="toggle"><input type="checkbox" id="only-held" checked> Only cards I hold</label>' if owned else ""}
    <ul>{"".join(nav)}</ul>
  </aside>
  <div class="main">
    <p class="intro">Everything CardPerks knows about each card: the fee, each benefit with what it is worth per period and per year, and the wording that identifies it on a statement. Amounts come from the issuer page linked on each card; "your value" marks perks the holder prices themselves. Type what each benefit is worth to you in the last column and the card's "My credits" and "My net" figures follow; those numbers stay in this browser. To correct an entry, drop a file in <code>config/cardperks/catalog/</code>; see docs/CATALOG.md.</p>
    {"".join(sections)}
  </div>
</div>
<script>
  const only = document.getElementById("only-held");
  if (only) {{
    try {{ if (localStorage.getItem("cardperks.onlyHeld") === "0") only.checked = false; }} catch (e) {{}}
    const apply = () => {{
      document.body.classList.toggle("only-held", only.checked);
      try {{ localStorage.setItem("cardperks.onlyHeld", only.checked ? "1" : "0"); }} catch (e) {{}}
    }};
    only.addEventListener("change", apply);
    apply();
  }}
  const money = (v) => (v < 0 ? "-$" : "$") + Math.abs(Math.round(v)).toLocaleString();
  const keyOf = (i) => "cardperks.my." + i.dataset.p + "." + i.dataset.b;
  const total = (section) => {{
    let sum = 0;
    section.querySelectorAll("input.my").forEach((i) => {{ sum += Number(i.value) || 0; }});
    const fee = Number(section.dataset.fee) || 0;
    const credits = section.querySelector("[data-my-credits]");
    const net = section.querySelector("[data-my-net]");
    if (credits) credits.textContent = money(sum);
    if (net) {{ net.textContent = money(sum - fee); net.classList.toggle("negative", sum - fee < 0); }}
  }};
  document.querySelectorAll("input.my").forEach((i) => {{
    try {{ const saved = localStorage.getItem(keyOf(i)); if (saved !== null) i.value = saved; }} catch (e) {{}}
    i.addEventListener("input", () => {{
      i.value = i.value.replace(/[^0-9.]/g, "");
      try {{ localStorage.setItem(keyOf(i), i.value); }} catch (e) {{}}
      total(i.closest("section"));
    }});
  }});
  document.querySelectorAll("th .reset").forEach((a) => {{
    a.addEventListener("click", (ev) => {{
      ev.preventDefault();
      const section = a.closest("section");
      section.querySelectorAll("input.my").forEach((i) => {{
        i.value = i.dataset.default;
        try {{ localStorage.removeItem(keyOf(i)); }} catch (e) {{}}
      }});
      total(section);
    }});
  }});
  document.querySelectorAll("section.product").forEach(total);
  // Best card for a purchase: rank by multiplier times the viewer's cents per point.
  const data = JSON.parse(document.getElementById("cp-data").textContent);
  const centsFor = {{}};
  document.querySelectorAll("input.cents").forEach((i) => {{
    try {{ const saved = localStorage.getItem("cardperks.cents." + i.dataset.currency); if (saved !== null) i.value = saved; }} catch (e) {{}}
    centsFor[i.dataset.currency] = Number(i.value) || 0;
    i.addEventListener("input", () => {{
      i.value = i.value.replace(/[^0-9.]/g, "");
      centsFor[i.dataset.currency] = Number(i.value) || 0;
      try {{ localStorage.setItem("cardperks.cents." + i.dataset.currency, i.value); }} catch (e) {{}}
      rank();
    }});
  }});
  const pick = document.getElementById("lookup-category");
  const list = document.getElementById("lookup-ranking");
  const rank = () => {{
    const cat = pick.value;
    const rows = [];
    data.forEach((p) => {{
      let hits = p.rates.filter((r) => r.c === cat);
      if (!hits.length && cat !== "other") hits = p.rates.filter((r) => r.c === "other");
      if (!hits.length) return;
      const best = hits.reduce((a, b) => (b.x > a.x ? b : a));
      const cents = centsFor[p.currency] ?? p.cents;
      rows.push({{ p, best, value: best.x * cents, base: !hits.some((r) => r.c === cat) }});
    }});
    rows.sort((a, b) => b.value - a.value || (b.p.held - a.p.held));
    list.innerHTML = "";
    if (!rows.length) {{ list.innerHTML = '<li><span class="empty">No card in the catalog lists a rate here.</span></li>'; return; }}
    let n = 0;
    rows.forEach((r) => {{
      const li = document.createElement("li");
      li.className = r.p.held ? "held" : "not-held";
      if (r.p.held) {{ n += 1; if (n === 1) li.classList.add("top"); }}
      const rate = document.createElement("span");
      rate.className = "rate";
      rate.title = r.best.n;
      rate.innerHTML = `${{r.best.x}}&times; ${{r.p.currency}}<small>≈ ${{r.value.toFixed(1)}}¢ per $${{r.base ? " · base rate" : ""}}</small>`;
      li.innerHTML = `<span class="rank">${{r.p.held ? n : "·"}}</span><span class="who"><a href="#${{r.p.id}}">${{r.p.name}}</a><small>${{r.p.issuer}}${{r.best.n ? " · " + r.best.n : ""}}</small></span>`;
      li.appendChild(rate);
      list.appendChild(li);
    }});
  }};
  try {{ const savedCat = localStorage.getItem("cardperks.lookupCategory"); if (savedCat && [...pick.options].some((o) => o.value === savedCat)) pick.value = savedCat; }} catch (e) {{}}
  pick.addEventListener("change", () => {{ try {{ localStorage.setItem("cardperks.lookupCategory", pick.value); }} catch (e) {{}} rank(); }});
  document.getElementById("cents-reset").addEventListener("click", (ev) => {{
    ev.preventDefault();
    document.querySelectorAll("input.cents").forEach((i) => {{
      i.value = i.dataset.default; centsFor[i.dataset.currency] = Number(i.value) || 0;
      try {{ localStorage.removeItem("cardperks.cents." + i.dataset.currency); }} catch (e) {{}}
    }});
    rank();
  }});
  if (only) only.addEventListener("change", rank);
  rank();
  const q = document.getElementById("q");
  q.addEventListener("input", () => {{
    const term = q.value.trim().toLowerCase();
    document.querySelectorAll(".product:not(.lookup)").forEach((section) => {{
      let any = false;
      const name = section.querySelector("h2").textContent.toLowerCase();
      section.querySelectorAll("tbody tr").forEach((tr) => {{
        const hit = !term || tr.textContent.toLowerCase().includes(term) || name.includes(term);
        tr.classList.toggle("hidden", !hit);
        any = any || hit;
      }});
      section.classList.toggle("hidden", !any);
    }});
  }});
</script>
</body></html>
"""
