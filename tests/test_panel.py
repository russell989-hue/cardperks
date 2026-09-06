"""The catalog page and its sidebar entry."""

from homeassistant.components import frontend
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cardperks.catalog_page import render_catalog


async def test_catalog_page_is_served_and_in_the_sidebar(
    hass, hass_client_no_auth, setup_integration: MockConfigEntry
):
    """Reachable from the left menu, and readable in an iframe without a token."""
    assert frontend.async_panel_exists(hass, "cardperks-catalog")

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

    css = await client.get("/cardperks/static/fonts.css")
    assert css.status == 200 and "Newsreader" in await css.text()
    font = await client.get("/cardperks/static/fonts/newsreader.woff2")
    assert font.status == 200 and (await font.read())[:4] == b"wOF2"

    await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert not frontend.async_panel_exists(hass, "cardperks-catalog")


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
