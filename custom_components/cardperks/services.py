"""Services: SUB spend, perk valuation, rotating categories, imports, catalog patterns."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .catalog_write import write_override
from .const import (
    ATTR_AMOUNT,
    ATTR_APPLY_FEE,
    ATTR_BENEFIT_ID,
    ATTR_CATEGORY,
    ATTR_CSV,
    ATTR_DATE,
    ATTR_DEVICE_ID,
    ATTR_NOTE,
    ATTR_PATH,
    ATTR_PATTERN,
    ATTR_QUARTER,
    ATTR_VALUE,
    DATA_IMPORTING,
    DOMAIN,
    OVERRIDE_DIR,
    SERVICE_ACTIVATE_ROTATING_CATEGORY,
    SERVICE_ADD_STATEMENT_MATCH,
    SERVICE_ADD_SUB_SPEND,
    SERVICE_IMPORT_CARDS,
    SERVICE_IMPORT_STATEMENT,
    SERVICE_SET_PERK_VALUE,
)
from .coordinator import CardPerksCoordinator
from .helpers import async_get_catalog, override_dir
from .importer import async_import_cards
from .statement_apply import (
    apply_statement,
    cards_for_issuer,
    cards_in_statement,
    subentry_last4s,
)
from .statements import parse_statement

IMPORT_CARDS_SCHEMA = vol.Schema({vol.Required(ATTR_CSV): cv.string})

IMPORT_STATEMENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PATH): cv.string,
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_APPLY_FEE, default=True): cv.boolean,
    }
)

ADD_STATEMENT_MATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_BENEFIT_ID): cv.string,
        vol.Required(ATTR_PATTERN): cv.string,
    }
)

ADD_SUB_SPEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_AMOUNT): vol.Coerce(float),
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)

SET_PERK_VALUE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_BENEFIT_ID): cv.string,
        vol.Required(ATTR_VALUE): vol.Coerce(float),
    }
)

ACTIVATE_ROTATING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_CATEGORY): cv.string,
        vol.Optional(ATTR_QUARTER): vol.Match(r"^\d{4}-Q[1-4]$"),
    }
)


def _resolve_card(hass: HomeAssistant, device_id: str) -> tuple[CardPerksCoordinator, str]:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_device")
    held_card_id = next(
        (
            ident
            for dom, ident in device.identifiers
            if dom == DOMAIN and not ident.startswith("owner:")
        ),
        None,
    )
    if held_card_id is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_card_device")
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: CardPerksCoordinator = entry.runtime_data
        if held_card_id in coordinator.cards:
            return coordinator, held_card_id
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_card")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_sub_spend(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.add_sub_spend(
            card_id, call.data[ATTR_AMOUNT], call.data.get(ATTR_DATE), call.data.get(ATTR_NOTE)
        )

    async def set_perk_value(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.set_perk_value(card_id, call.data[ATTR_BENEFIT_ID], call.data[ATTR_VALUE])

    async def activate_rotating_category(call: ServiceCall) -> None:
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        coordinator.activate_rotating_category(
            card_id, call.data[ATTR_CATEGORY], call.data.get(ATTR_QUARTER)
        )

    async def import_cards(call: ServiceCall) -> ServiceResponse:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_set_up")
        entry = entries[0]
        catalog = await async_get_catalog(hass)
        # Suppress the per-subentry reload while importing; reload once at the end.
        hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
        try:
            result = await async_import_cards(hass, entry, catalog, call.data[ATTR_CSV])
        finally:
            hass.data[DOMAIN][DATA_IMPORTING] = False
        if result.created_owners or result.created_cards:
            await hass.config_entries.async_reload(entry.entry_id)
        return result.as_dict()

    async def import_statement(call: ServiceCall) -> ServiceResponse:
        """Import an issuer export from a file on the box.

        The building block for a watched folder: point an automation's folder_watcher
        at `/config/cardperks/statements/` and call this with the new file's path.
        Cards are picked by the numbers in the file, or the one card on the file's
        issuer, so the normal loop is download, drop in the folder, done.
        """
        path = Path(call.data[ATTR_PATH])
        if not path.is_absolute():
            path = Path(hass.config.path(str(path)))
        # The integration's own folder under config/ is always fine; anything else has
        # to be in allowlist_external_dirs, the same rule the rest of HA applies.
        own_folder = Path(hass.config.path(OVERRIDE_DIR)).resolve()
        inside_own = path.resolve().is_relative_to(own_folder) if path.exists() else False
        if not inside_own and not hass.config.is_allowed_path(str(path)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="statement_path_not_allowed",
                translation_placeholders={"path": str(path)},
            )

        def _read() -> str:
            raw = path.read_bytes()
            for enc in ("utf-8-sig", "utf-16", "cp1252"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")

        try:
            text = await hass.async_add_executor_job(_read)
        except OSError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="statement_file_missing",
                translation_placeholders={"path": str(path)},
            ) from err
        try:
            parsed = parse_statement(text, path.name)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="statement_unrecognised",
                translation_placeholders={"path": str(path)},
            ) from err

        if call.data.get(ATTR_DEVICE_ID):
            coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
            entry = coordinator.config_entry
            targets = [card_id]
        else:
            entries = hass.config_entries.async_loaded_entries(DOMAIN)
            if not entries:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="not_set_up"
                )
            entry = entries[0]
            coordinator = entry.runtime_data
            subs = cards_in_statement(entry, parsed)
            if not subs:
                # No per-row numbers (Amex): the issuer's only card, or the one the
                # filename names.
                subs = cards_for_issuer(entry, coordinator.catalog, parsed.issuer)
                if parsed.filename_last4:
                    subs = [s for s in subs if parsed.filename_last4 in subentry_last4s(s)] or subs
                if len(subs) != 1:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="statement_no_card",
                        translation_placeholders={"path": path.name, "issuer": parsed.issuer},
                    )
            targets = [s.subentry_id for s in subs]

        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        results = [
            apply_statement(
                hass,
                entry,
                card_id,
                parsed,
                file_hash=file_hash,
                filename=path.name,
                apply_fee=call.data[ATTR_APPLY_FEE],
            )
            for card_id in targets
        ]
        known: set[str] = set()
        for card_id in targets:
            known |= coordinator.card(card_id).all_last4
        return {
            "file": path.name,
            "issuer": parsed.issuer,
            "cards": [r.as_dict() for r in results],
            "unassigned_last4": sorted(parsed.last4s - known),
        }

    async def add_statement_match(call: ServiceCall) -> ServiceResponse:
        """Teach the catalog a credit line, from the import result, without editing JSON.

        Writes the whole product into the override folder with the pattern added, then
        reloads so the next import picks the line up. The override replaces the shipped
        product from then on, which is how overrides work.
        """
        coordinator, card_id = _resolve_card(hass, call.data[ATTR_DEVICE_ID])
        card = coordinator.card(card_id)
        benefit = coordinator.benefit(card, call.data[ATTR_BENEFIT_ID])
        pattern = call.data[ATTR_PATTERN].strip()
        try:
            re.compile(pattern, re.I)
        except re.error as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_pattern",
                translation_placeholders={"pattern": pattern, "error": str(err)},
            ) from err
        product = coordinator.catalog.get(card.product_id)
        assert product is not None
        if pattern in benefit.statement_match:
            return {
                "changed": False,
                "benefit": benefit.id,
                "patterns": list(benefit.statement_match),
            }
        new_benefit = replace(benefit, statement_match=(*benefit.statement_match, pattern))
        new_product = replace(
            product,
            benefits=tuple(new_benefit if b.id == benefit.id else b for b in product.benefits),
        )
        written = await hass.async_add_executor_job(write_override, override_dir(hass), new_product)
        # Setup reloads the catalog from disk, overrides included.
        await hass.config_entries.async_reload(coordinator.config_entry.entry_id)
        return {
            "changed": True,
            "file": str(written),
            "benefit": benefit.id,
            "patterns": list(new_benefit.statement_match),
        }

    hass.services.async_register(DOMAIN, SERVICE_ADD_SUB_SPEND, add_sub_spend, ADD_SUB_SPEND_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATEMENT,
        import_statement,
        IMPORT_STATEMENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_STATEMENT_MATCH,
        add_statement_match,
        ADD_STATEMENT_MATCH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_CARDS,
        import_cards,
        IMPORT_CARDS_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PERK_VALUE, set_perk_value, SET_PERK_VALUE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_ROTATING_CATEGORY,
        activate_rotating_category,
        ACTIVATE_ROTATING_SCHEMA,
    )
