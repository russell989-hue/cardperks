"""Render the catalog as one readable HTML page. Pure: takes a Catalog, returns a string.

Served live by the sidebar panel, so overrides and reloads show up at once. Carries
only catalog data, never anything about held cards, which is why it can be served
without a login (see panel.py).
"""

from __future__ import annotations

import html
from datetime import date

from .const import BenefitType, Cadence, ResetRule
from .models import Catalog

CADENCE_WORDS = {
    Cadence.MONTHLY: "monthly",
    Cadence.QUARTERLY: "quarterly",
    Cadence.SEMIANNUAL: "every 6 months",
    Cadence.ANNUAL: "yearly",
    Cadence.PER_ANNIVERSARY: "each anniversary",
    Cadence.ONE_TIME: "one-time",
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


def render_catalog(
    catalog: Catalog,
    *,
    source_note: str = "",
    fonts_href: str = "/cardperks/static/fonts.css",
    owned: frozenset[str] = frozenset(),
) -> str:
    """The whole catalog as an HTML document (title and styles included).

    `owned` is the set of product ids the household holds: those products are marked,
    and the page opens showing only them, with a toggle for the rest.
    """
    by_issuer = catalog.by_issuer()
    issuer_names = catalog.issuers()
    today = date.today().isoformat()

    nav: list[str] = []
    sections: list[str] = []
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
                        '<ul class="eligible">'
                        + "".join(f"<li>{_esc(e)}</li>" for e in b.eligible)
                        + "</ul>"
                        if b.eligible
                        else ""
                    )
                    + "</td>"
                    f'<td><span class="type type-{b.type.value}">{TYPE_WORDS[b.type]}</span></td>'
                    f'<td class="num">{amount}</td>'
                    f"<td>{_esc(cadence)}</td>"
                    f'<td class="num">{_money(per_year) if per_year else ""}</td>'
                    f'<td class="match">{match}</td>'
                    "</tr>"
                )
            au = p.au_terms
            au_text = f"Additional card {_money(au.fee)}" if au.fee else "Additional cards free"
            if au.notes:
                au_text += f". {au.notes}"
            chips = ""
            if held:
                chips += '<span class="chip chip-held">you hold this</span>'
            if p.needs_verification:
                chips += '<span class="chip chip-flag">needs verification</span>'
            if p.origin != "shipped":
                chips += f'<span class="chip chip-over" title="{_esc(p.origin)}">override</span>'
            sections.append(
                f'<section class="product {"held" if held else "not-held"}" id="{_esc(p.id)}">'
                '<header class="p-head">'
                f'<div><p class="eyebrow">{_esc(p.issuer_name)}</p>'
                f"<h2>{_esc(p.name)} {chips}</h2>"
                f'<p class="p-meta">{_esc(au_text)}. Checked {_esc(p.last_verified.isoformat())} '
                f'against <a href="{_esc(p.source_url)}" target="_blank" rel="noopener">the issuer '
                f"page</a>. Catalog id <code>{_esc(p.id)}</code>.</p></div>"
                '<dl class="p-figures">'
                f"<div><dt>Annual fee</dt><dd>{_money(p.annual_fee)}</dd></div>"
                f"<div><dt>Credits per year</dt><dd>{_money(annual)}</dd></div>"
                f"<div><dt>Benefits</dt><dd>{len(p.benefits)}</dd></div></dl>"
                "</header>"
                '<div class="table-wrap"><table>'
                '<thead><tr><th>Benefit</th><th>Type</th><th class="num">Per period</th>'
                '<th>Cadence</th><th class="num">Per year</th><th>Statement match</th></tr></thead>'
                f"<tbody>{''.join(rows)}</tbody></table></div>"
                "</section>"
            )

    summary = f"{total_products} products"
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
.eligible {{ margin: 6px 0 0; padding-left: 16px; color: var(--ink-2); font-size: 12.5px; max-width: 58ch; }}
.eligible li {{ margin: 2px 0; }}
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
.chip-over {{ background: var(--brass-soft); color: var(--brass); }}
.muted {{ color: var(--ink-3); font-size: 12px; }}
.hidden {{ display: none; }}
@media (max-width: 820px) {{ .page {{ grid-template-columns: 1fr; gap: 20px; }} .side {{ position: static; }} .p-figures {{ gap: 18px; }} }}
@media (prefers-reduced-motion: no-preference) {{ html {{ scroll-behavior: smooth; }} }}
</style></head><body>
<div class="page">
  <aside class="side">
    <h1>CardPerks Catalog</h1>
    <p class="sub">{_esc(summary)}. {_esc(source_note) or f"Rendered {today}."}</p>
    <input type="search" id="q" placeholder="Filter benefits…" aria-label="Filter benefits">
    {'<label class="toggle"><input type="checkbox" id="only-held" checked> Only cards I hold</label>' if owned else ""}
    <ul>{"".join(nav)}</ul>
  </aside>
  <div class="main">
    <p class="intro">Everything CardPerks knows about each card: the fee, each benefit with what it is worth per period and per year, and the wording that identifies it on a statement. Amounts come from the issuer page linked on each card; "your value" marks perks the holder prices themselves. To correct an entry, drop a file in <code>config/cardperks/catalog/</code>; see docs/CATALOG.md.</p>
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
  const q = document.getElementById("q");
  q.addEventListener("input", () => {{
    const term = q.value.trim().toLowerCase();
    document.querySelectorAll(".product").forEach((section) => {{
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
