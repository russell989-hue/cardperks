"""The catalog page the integration serves, shown by an iframe card in the dashboard.

The page is rendered on every request from the catalog currently loaded, so a new
override file or a reload shows up without restarting anything. It is served without
a login because an iframe cannot pass one along, and because it carries catalog data
only: no card, owner, balance or statement ever appears on it. The generated
dashboard's "Catalog" view (tools/build_card_views.py) is an iframe over PAGE_URL.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.http import KEY_HASS

from .catalog_page import render_catalog
from .const import DOMAIN
from .helpers import DATA_CATALOG

PAGE_URL = "/cardperks/catalog"
STATIC_URL = "/cardperks/static"
WWW_DIR = Path(__file__).parent / "www"
DATA_STATIC = "static_registered"
DATA_PANEL = "page_registered"


class CatalogPageView(HomeAssistantView):
    """GET /cardperks/catalog: the rendered catalog."""

    url = PAGE_URL
    name = "cardperks:catalog"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        """Render from the catalog currently loaded. Serves only; never fetches."""
        hass: HomeAssistant = request.app[KEY_HASS]
        catalog = hass.data.get(DOMAIN, {}).get(DATA_CATALOG)
        if catalog is None:
            return web.Response(status=503, text="CardPerks is not loaded yet.")
        owned: set[str] = set()
        my_values: dict[str, dict[str, float]] = {}
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            data = entry.runtime_data.data
            for c in entry.runtime_data.cards.values():
                if c.status == "cancelled":
                    continue
                owned.add(c.product_id)
                product = catalog.get(c.product_id)
                if product is None:
                    continue
                # A perk's yearly value is what this household set for it (shared perks
                # are already split); the first held card of a product speaks for it.
                mine = my_values.setdefault(c.product_id, {})
                for b in product.benefits_for(c):
                    if b.type.value in ("perk", "insurance") and b.id not in mine:
                        mine[b.id] = b.annual_value(data.perk_values.get(c.id, {}).get(b.id))
        body = await hass.async_add_executor_job(
            partial(
                render_catalog,
                catalog,
                source_note="Live from Home Assistant, overrides included.",
                owned=frozenset(owned),
                my_values=my_values,
            )
        )
        return web.Response(text=body, content_type="text/html", charset="utf-8")


async def async_register_static(hass: HomeAssistant) -> None:
    """Serve the integration's www folder: the fonts the theme and the catalog page use."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_STATIC):
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(WWW_DIR), cache_headers=True)]
    )
    data[DATA_STATIC] = True


@callback
def async_register_page(hass: HomeAssistant) -> None:
    """Serve the catalog page. Safe to call more than once."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_PANEL):
        return
    hass.http.register_view(CatalogPageView())
    data[DATA_PANEL] = True
