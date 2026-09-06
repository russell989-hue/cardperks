"""The catalog as a sidebar entry: a page the integration serves, shown in an iframe.

The page is rendered on every request from the catalog currently loaded, so a new
override file or a reload shows up without restarting anything. It is served without
a login because Home Assistant's iframe panels cannot pass one along, and because it
carries catalog data only: no card, owner, balance or statement ever appears on it.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.http import KEY_HASS

from .catalog_page import render_catalog
from .const import DOMAIN
from .helpers import DATA_CATALOG

PANEL_URL_PATH = "cardperks-catalog"
PAGE_URL = "/cardperks/catalog"
STATIC_URL = "/cardperks/static"
WWW_DIR = Path(__file__).parent / "www"
DATA_STATIC = "static_registered"
DATA_PANEL = "panel_registered"


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
        body = await hass.async_add_executor_job(
            partial(
                render_catalog, catalog, source_note="Live from Home Assistant, overrides included."
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
def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the page and add the sidebar entry. Safe to call more than once."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(DATA_PANEL):
        return
    hass.http.register_view(CatalogPageView())
    frontend.async_register_built_in_panel(
        hass,
        "iframe",
        sidebar_title="Card catalog",
        sidebar_icon="mdi:credit-card-search-outline",
        frontend_url_path=PANEL_URL_PATH,
        config={"url": PAGE_URL},
        require_admin=False,
    )
    data[DATA_PANEL] = True


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    data = hass.data.get(DOMAIN, {})
    if data.pop(DATA_PANEL, None):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
