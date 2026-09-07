"""The catalog page the dashboard's Catalog view embeds."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.catalog_page import render_catalog


async def test_catalog_page_is_served(
    hass, hass_client_no_auth, setup_integration: MockConfigEntry
):
    """Readable in an iframe card without a token, and carrying catalog data only."""
    client = await hass_client_no_auth()
    resp = await client.get("/cardperks/catalog")
    assert resp.status == 200
    body = await resp.text()
    assert "<title>CardPerks Catalog</title>" in body
    assert "Premium Card" in body and "Monthly credit" in body
    assert "overrides included" in body
    # Catalog only: nothing about the household leaks onto a page without a login.
    assert "1234" not in body and "Brian" not in body
    assert "/cardperks/static/fonts.css" in body
    # The household's products are marked and the page opens on them; the rest is a toggle.
    assert "you hold this" in body and 'id="only-held" checked' in body
    assert '<section class="product held" id="test_premium"' in body
    assert '<section class="product not-held" id="test_basic"' in body
    # A My-value box per benefit: credits start at the catalog's yearly amount, perks at
    # what this household values them at, and the totals live in the header.
    assert 'data-p="test_premium" data-b="monthly_credit" data-default="120" value="120"' in body
    assert 'data-p="test_premium" data-b="lounge" data-default="100" value="100"' in body
    assert "data-my-credits" in body and "data-my-net" in body and 'data-fee="500.0"' in body
    # The best-card lookup: category picker, per-currency cents, and the rates as data.
    assert 'id="lookup-category"' in body and 'data-currency="Test points"' in body
    assert '"rates": [{"c": "dining", "x": 3.0, "n": "Restaurants worldwide"}' in body
    assert "Earns Test points: <span" in body and "3&times; dining</span>" in body
    assert "1&times; everything else</span>." in body
    # Adding an authorized user: the premium card's AU terms and AU-facing benefits.
    assert 'id="authorized-users"' in body and "Lounge access" in body
    assert '<td class="num">$50</td><td>Yes</td>' in body

    css = await client.get("/cardperks/static/fonts.css")
    assert css.status == 200 and "Newsreader" in await css.text()
    font = await client.get("/cardperks/static/fonts/newsreader.woff2")
    assert font.status == 200 and (await font.read())[:4] == b"wOF2"


def test_render_catalog_marks_overrides_and_flags(catalog):
    from dataclasses import replace

    from custom_components.cardperks.models import Catalog

    p = catalog.get("test_premium")
    tweaked = replace(p, origin="/config/cardperks/catalog/testbank.json", needs_verification=True)
    body = render_catalog(Catalog(products={**catalog.products, p.id: tweaked}))
    assert "1 still to verify" in body and "1 overridden" in body
    assert 'class="chip chip-over"' in body and "needs verification" in body
    # Dollars per year add up the way the entities do: $10 monthly is $120.
    assert "$120" in body
