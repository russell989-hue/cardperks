"""Config flow: one household entry with owner and held-card subentries."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_ANNUAL_FEE,
    CONF_CLOSE_DATE,
    CONF_FEE_MONTH,
    CONF_FIRST_OWNER,
    CONF_HOUSEHOLD_NAME,
    CONF_ISSUER,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_NOTES,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PRODUCT_ID,
    CONF_ROLE,
    DOMAIN,
    SUBENTRY_CARD,
    SUBENTRY_OWNER,
    Role,
)
from .helpers import async_get_catalog
from .importer import parse_date
from .models import Catalog

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip

LAST4_RE = re.compile(r"^\d{4}$")


def _month_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=str(i + 1), label=name) for i, name in enumerate(MONTH_NAMES)
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class CardPerksConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_OWNER: OwnerSubentryFlow, SUBENTRY_CARD: HeldCardSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            first_owner = user_input[CONF_FIRST_OWNER].strip()
            if not first_owner:
                errors[CONF_FIRST_OWNER] = "name_required"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_HOUSEHOLD_NAME].strip() or "Home",
                    data={},
                    subentries=[
                        ConfigSubentryData(
                            subentry_type=SUBENTRY_OWNER,
                            title=first_owner,
                            unique_id=slugify(first_owner),
                            data={CONF_NAME: first_owner},
                        )
                    ],
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOUSEHOLD_NAME, default="Home"): TextSelector(),
                vol.Required(CONF_FIRST_OWNER): TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class OwnerSubentryFlow(ConfigSubentryFlow):
    def _slug_taken(self, slug: str, ignore: str | None = None) -> bool:
        return any(
            sub.subentry_type == SUBENTRY_OWNER
            and sub.unique_id == slug
            and sub.subentry_id != ignore
            for sub in self._get_entry().subentries.values()
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            slug = slugify(name)
            if not name:
                errors[CONF_NAME] = "name_required"
            elif self._slug_taken(slug):
                return self.async_abort(reason="already_configured")
            else:
                return self.async_create_entry(title=name, data={CONF_NAME: name}, unique_id=slug)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME): TextSelector()}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            slug = slugify(name)
            if not name:
                errors[CONF_NAME] = "name_required"
            elif self._slug_taken(slug, ignore=subentry.subentry_id):
                errors[CONF_NAME] = "already_configured"
            else:
                return self.async_update_and_abort(
                    entry, subentry, title=name, data={CONF_NAME: name}, unique_id=slug
                )
        schema = vol.Schema({vol.Required(CONF_NAME): TextSelector()})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_NAME: subentry.title}),
            errors=errors,
        )


class HeldCardSubentryFlow(ConfigSubentryFlow):
    def __init__(self) -> None:
        super().__init__()
        self._catalog: Catalog | None = None
        self._data: dict[str, Any] = {}

    async def _catalog_or_load(self) -> Catalog:
        if self._catalog is None:
            self._catalog = await async_get_catalog(self.hass)
        return self._catalog

    def _owners(self) -> list[ConfigSubentry]:
        return [
            s for s in self._get_entry().subentries.values() if s.subentry_type == SUBENTRY_OWNER
        ]

    def _cards(self) -> list[ConfigSubentry]:
        return [
            s for s in self._get_entry().subentries.values() if s.subentry_type == SUBENTRY_CARD
        ]

    # ---- step 1: owner, issuer, role
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        catalog = await self._catalog_or_load()
        owners = self._owners()
        if not owners:
            return self.async_abort(reason="no_owners")
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_product()

        issuers = catalog.issuers()
        schema = vol.Schema(
            {
                vol.Required(CONF_OWNER_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=o.subentry_id, label=o.title) for o in owners
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_ISSUER): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=slug, label=name)
                            for slug, name in sorted(issuers.items(), key=lambda kv: kv[1])
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_ROLE, default=str(Role.PRIMARY)): SelectSelector(
                    SelectSelectorConfig(
                        options=[str(r) for r in Role],
                        translation_key="role",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    # ---- step 2: product (+ parent card for AU)
    async def async_step_product(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        catalog = await self._catalog_or_load()
        issuer = self._data[CONF_ISSUER]
        role = Role(self._data[CONF_ROLE])
        products = catalog.by_issuer().get(issuer, [])
        errors: dict[str, str] = {}

        if user_input is not None:
            product_id = user_input[CONF_PRODUCT_ID]
            if role is Role.AUTHORIZED_USER:
                parents = [
                    c
                    for c in self._cards()
                    if c.data.get(CONF_PRODUCT_ID) == product_id
                    and Role(c.data.get(CONF_ROLE, "primary")) is Role.PRIMARY
                ]
                parent_id = user_input.get(CONF_PARENT_CARD_ID)
                if not parents or parent_id not in {p.subentry_id for p in parents}:
                    errors["base"] = "no_parent_card"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_details()

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_PRODUCT_ID): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=p.id, label=p.name) for p in products],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        }
        if role is Role.AUTHORIZED_USER:
            primaries = [
                c
                for c in self._cards()
                if Role(c.data.get(CONF_ROLE, "primary")) is Role.PRIMARY
                and catalog.get(c.data.get(CONF_PRODUCT_ID, "")) is not None
                and catalog.get(c.data[CONF_PRODUCT_ID]).issuer == issuer
            ]
            if not primaries:
                return self.async_abort(reason="no_parent_card")
            schema_dict[vol.Required(CONF_PARENT_CARD_ID)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=c.subentry_id, label=c.title) for c in primaries
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        return self.async_show_form(
            step_id="product", data_schema=vol.Schema(schema_dict), errors=errors
        )

    # ---- step 3: details
    def _details_schema(self, include_close: bool) -> vol.Schema:
        schema: dict[Any, Any] = {
            vol.Optional(CONF_OPEN_DATE): TextSelector(),
            vol.Optional(CONF_FEE_MONTH): _month_selector(),
            vol.Optional(CONF_LAST4): TextSelector(),
            vol.Optional(CONF_NICKNAME): TextSelector(),
            vol.Optional(CONF_ANNUAL_FEE): TextSelector(),
            vol.Optional(CONF_NOTES): TextSelector(),
        }
        if include_close:
            schema[vol.Optional(CONF_CLOSE_DATE)] = TextSelector()
        return vol.Schema(schema)

    def _validate_details(self, user_input: dict[str, Any], role: Role) -> dict[str, str]:
        errors: dict[str, str] = {}
        last4 = (user_input.get(CONF_LAST4) or "").strip()
        if last4 and not LAST4_RE.match(last4):
            errors[CONF_LAST4] = "invalid_last4"
        for key in (CONF_OPEN_DATE, CONF_CLOSE_DATE):
            raw = (user_input.get(key) or "").strip()
            if raw:
                try:
                    user_input[key] = parse_date(raw).isoformat()
                except ValueError:
                    errors[key] = "invalid_date"
        fee_raw = str(user_input.get(CONF_ANNUAL_FEE) or "").strip().lstrip("$")
        if fee_raw:
            try:
                user_input[CONF_ANNUAL_FEE] = float(fee_raw)
            except ValueError:
                errors[CONF_ANNUAL_FEE] = "invalid_fee"
        if (
            role is Role.PRIMARY
            and not user_input.get(CONF_OPEN_DATE)
            and not user_input.get(CONF_FEE_MONTH)
        ):
            errors["base"] = "need_anniversary"
        return errors

    def _normalise(self, user_input: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in (CONF_OPEN_DATE, CONF_CLOSE_DATE, CONF_LAST4, CONF_NICKNAME, CONF_NOTES):
            val = user_input.get(key)
            out[key] = (str(val).strip() or None) if val is not None else None
        fee = user_input.get(CONF_FEE_MONTH)
        out[CONF_FEE_MONTH] = int(fee) if fee else None
        af = user_input.get(CONF_ANNUAL_FEE)
        out[CONF_ANNUAL_FEE] = float(af) if af not in (None, "") else None
        return out

    async def _title_for(self, data: dict[str, Any]) -> str:
        if data.get(CONF_NICKNAME):
            return data[CONF_NICKNAME]
        catalog = await self._catalog_or_load()
        product = catalog.get(data[CONF_PRODUCT_ID])
        owner = next((o.title for o in self._owners() if o.subentry_id == data[CONF_OWNER_ID]), "?")
        name = product.name if product else data[CONF_PRODUCT_ID]
        suffix = f" ·{data[CONF_LAST4]}" if data.get(CONF_LAST4) else ""
        au = " (AU)" if Role(data.get(CONF_ROLE, "primary")) is Role.AUTHORIZED_USER else ""
        return f"{name}{au} ({owner}{suffix})"

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        role = Role(self._data[CONF_ROLE])
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate_details(user_input, role)
            if not errors:
                details = self._normalise(user_input)
                if role is Role.AUTHORIZED_USER:
                    parent = next(
                        (
                            c
                            for c in self._cards()
                            if c.subentry_id == self._data[CONF_PARENT_CARD_ID]
                        ),
                        None,
                    )
                    if parent is not None:
                        details[CONF_OPEN_DATE] = details[CONF_OPEN_DATE] or parent.data.get(
                            CONF_OPEN_DATE
                        )
                        details[CONF_FEE_MONTH] = details[CONF_FEE_MONTH] or parent.data.get(
                            CONF_FEE_MONTH
                        )
                data = {
                    CONF_OWNER_ID: self._data[CONF_OWNER_ID],
                    CONF_PRODUCT_ID: self._data[CONF_PRODUCT_ID],
                    CONF_ROLE: str(role),
                    CONF_PARENT_CARD_ID: self._data.get(CONF_PARENT_CARD_ID),
                    CONF_CLOSE_DATE: None,
                    **details,
                }
                return self.async_create_entry(title=await self._title_for(data), data=data)
        return self.async_show_form(
            step_id="details",
            data_schema=self._details_schema(include_close=False),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        role = Role(subentry.data.get(CONF_ROLE, "primary"))
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate_details(user_input, role)
            if not errors:
                data = {**subentry.data, **self._normalise(user_input)}
                self._data = dict(data)
                return self.async_update_and_abort(
                    entry, subentry, title=await self._title_for(data), data=data
                )
        current = {
            k: v
            for k, v in subentry.data.items()
            if k
            in (
                CONF_OPEN_DATE,
                CONF_FEE_MONTH,
                CONF_LAST4,
                CONF_NICKNAME,
                CONF_ANNUAL_FEE,
                CONF_NOTES,
                CONF_CLOSE_DATE,
            )
            and v is not None
        }
        if CONF_FEE_MONTH in current:
            current[CONF_FEE_MONTH] = str(current[CONF_FEE_MONTH])
        if CONF_ANNUAL_FEE in current:
            current[CONF_ANNUAL_FEE] = str(current[CONF_ANNUAL_FEE])
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                self._details_schema(include_close=True), current
            ),
            errors=errors,
        )
