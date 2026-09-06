"""Config flow: one household entry with owner and held-card subentries."""

from __future__ import annotations

import hashlib
import re
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
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
    BooleanSelector,
    DateSelector,
    FileSelector,
    FileSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util import slugify

from .const import (
    ATTR_ADOPT_LAST4,
    ATTR_APPLY_FEE,
    ATTR_CARD,
    ATTR_CSV,
    ATTR_FILE,
    CARD_COLORS,
    CONF_ANNUAL_FEE,
    CONF_CLOSE_DATE,
    CONF_COLOR,
    CONF_ENABLED_CONDITIONAL,
    CONF_FEE_MONTH,
    CONF_FIRST_OWNER,
    CONF_HOUSEHOLD_NAME,
    CONF_ISSUER,
    CONF_LAST4,
    CONF_NAME,
    CONF_NICKNAME,
    CONF_NOT_APPLICABLE,
    CONF_NOTES,
    CONF_OPEN_DATE,
    CONF_OWNER_ID,
    CONF_PARENT_CARD_ID,
    CONF_PREVIOUS_LAST4,
    CONF_PRODUCT_ID,
    CONF_PROGRAM,
    CONF_PROGRAM_ID,
    CONF_ROLE,
    CONF_SOURCE,
    CONF_TIER,
    CONF_TIER_ID,
    CONF_VALID_THROUGH,
    DATA_IMPORTING,
    DOMAIN,
    SUBENTRY_CARD,
    SUBENTRY_IMPORT,
    SUBENTRY_OWNER,
    SUBENTRY_STATEMENT,
    SUBENTRY_STATUS,
    Role,
)
from .helpers import async_get_catalog
from .importer import async_import_cards, parse_date
from .models import Catalog
from .statement_apply import (
    apply_statement,
    cards_for_issuer,
    cards_in_statement,
    subentry_last4s,
    summarise,
)
from .statements import ParsedStatement, decode_statement, latest_fee, parse_statement

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip

LAST4_RE = re.compile(r"^\d{4}$")


def _split_last4(raw: Any) -> list[str] | None:
    """Parse a comma or space separated list of card numbers. None if any is malformed."""
    if isinstance(raw, list):
        raw = ", ".join(raw)
    parts = [p for p in re.split(r"[,\s]+", str(raw or "").strip()) if p]
    if any(not LAST4_RE.match(p) for p in parts):
        return None
    return parts


def _conditions_text(product, role: Role) -> str:
    """Explain each conditional benefit so the user can tell if they qualify."""
    if product is None:
        return ""
    lines = [
        f"- **{b.name}**: {b.condition}" for b in product.conditional_benefits(role) if b.condition
    ]
    return "\n".join(lines) if lines else ""


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
        return {
            SUBENTRY_OWNER: OwnerSubentryFlow,
            SUBENTRY_CARD: HeldCardSubentryFlow,
            SUBENTRY_IMPORT: ImportSubentryFlow,
            SUBENTRY_STATEMENT: ImportStatementSubentryFlow,
            SUBENTRY_STATUS: StatusSubentryFlow,
        }

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


OTHER_PROGRAM = "__other__"


class StatusSubentryFlow(ConfigSubentryFlow):
    """Elite status earned outright (flights, nights, a match), not from a card.

    Card-granted status needs no entry: the catalog says what a card confers, and it
    shows up by itself while the card is held. Programs in the catalog offer their
    tiers as a pick list and bring their benefits along; any other program is typed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._first: dict[str, Any] = {}
        self._catalog: Catalog | None = None

    async def _catalog_or_load(self) -> Catalog:
        if self._catalog is None:
            self._catalog = await async_get_catalog(self.hass)
        return self._catalog

    def _owners(self) -> list[ConfigSubentry]:
        return [
            s for s in self._get_entry().subentries.values() if s.subentry_type == SUBENTRY_OWNER
        ]

    def _first_schema(self, catalog: Catalog) -> vol.Schema:
        programs = sorted(catalog.programs.values(), key=lambda p: p.name)
        options = [SelectOptionDict(value=p.id, label=p.name) for p in programs]
        options.append(SelectOptionDict(value=OTHER_PROGRAM, label="Another program"))
        return vol.Schema(
            {
                vol.Required(CONF_OWNER_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=o.subentry_id, label=o.title)
                            for o in self._owners()
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_PROGRAM_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                ),
            }
        )

    def _details_schema(self, program) -> vol.Schema:
        fields: dict[Any, Any] = {}
        if program is not None:
            fields[vol.Required(CONF_TIER_ID)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=t.id, label=t.name)
                        for t in sorted(program.tiers, key=lambda t: t.rank)
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            fields[vol.Required(CONF_PROGRAM)] = TextSelector()
            fields[vol.Required(CONF_TIER)] = TextSelector()
        fields[vol.Optional(CONF_VALID_THROUGH)] = DateSelector()
        fields[vol.Optional(CONF_SOURCE)] = TextSelector()
        fields[vol.Optional(CONF_NOTES)] = TextSelector(TextSelectorConfig(multiline=True))
        return vol.Schema(fields)

    def _clean(self, program, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        errors: dict[str, str] = {}
        if program is not None:
            tier = program.tier(user_input.get(CONF_TIER_ID))
            if tier is None:
                errors[CONF_TIER_ID] = "tier_required"
            program_name, tier_name, tier_id, program_id = (
                program.name,
                tier.name if tier else "",
                tier.id if tier else None,
                program.id,
            )
        else:
            program_name = (user_input.get(CONF_PROGRAM) or "").strip()
            tier_name = (user_input.get(CONF_TIER) or "").strip()
            tier_id = program_id = None
            if not program_name:
                errors[CONF_PROGRAM] = "program_required"
            if not tier_name:
                errors[CONF_TIER] = "tier_required"
        valid = user_input.get(CONF_VALID_THROUGH)
        data = {
            CONF_OWNER_ID: self._first[CONF_OWNER_ID],
            CONF_PROGRAM_ID: program_id,
            CONF_PROGRAM: program_name,
            CONF_TIER_ID: tier_id,
            CONF_TIER: tier_name,
            CONF_VALID_THROUGH: str(valid) if valid else None,
            CONF_SOURCE: (user_input.get(CONF_SOURCE) or "").strip() or None,
            CONF_NOTES: (user_input.get(CONF_NOTES) or "").strip() or None,
        }
        return data, errors

    def _title(self, data: dict[str, Any]) -> str:
        owner = next((o.title for o in self._owners() if o.subentry_id == data[CONF_OWNER_ID]), "?")
        return f"{data[CONF_PROGRAM]} {data[CONF_TIER]} ({owner})"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._owners():
            return self.async_abort(reason="no_owners")
        catalog = await self._catalog_or_load()
        if user_input is not None:
            self._first = dict(user_input)
            return await self.async_step_details()
        return self.async_show_form(step_id="user", data_schema=self._first_schema(catalog))

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        catalog = await self._catalog_or_load()
        program = catalog.programs.get(self._first.get(CONF_PROGRAM_ID) or "")
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._clean(program, user_input)
            if not errors:
                if self.source == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=self._title(data),
                        data=data,
                    )
                return self.async_create_entry(title=self._title(data), data=data)
        suggested = {k: v for k, v in self._first.items() if v is not None}
        return self.async_show_form(
            step_id="details",
            data_schema=self.add_suggested_values_to_schema(
                self._details_schema(program), suggested
            ),
            errors=errors,
            description_placeholders={"program": program.name if program else "the program"},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        catalog = await self._catalog_or_load()
        current = dict(self._get_reconfigure_subentry().data)
        if user_input is not None:
            self._first = {**current, **user_input}
            return await self.async_step_details()
        suggested = {
            CONF_OWNER_ID: current.get(CONF_OWNER_ID),
            CONF_PROGRAM_ID: current.get(CONF_PROGRAM_ID) or OTHER_PROGRAM,
        }
        self._first = current
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(self._first_schema(catalog), suggested),
        )


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
    def _conditional_options(self, product_id: str, role: Role) -> list[SelectOptionDict]:
        catalog = self._catalog
        product = catalog.get(product_id) if catalog else None
        if product is None:
            return []
        return [
            SelectOptionDict(value=b.id, label=b.label) for b in product.conditional_benefits(role)
        ]

    def _benefit_options(self, product_id: str, role: Role) -> list[SelectOptionDict]:
        product = self._catalog.get(product_id) if self._catalog else None
        if product is None:
            return []
        return [
            SelectOptionDict(value=b.id, label=b.label) for b in product.benefits_for_role(role)
        ]

    def _details_schema(
        self,
        include_close: bool,
        conditional: list[SelectOptionDict] | None = None,
        benefits: list[SelectOptionDict] | None = None,
    ) -> vol.Schema:
        schema: dict[Any, Any] = {
            vol.Optional(CONF_OPEN_DATE): TextSelector(),
            vol.Optional(CONF_FEE_MONTH): _month_selector(),
            vol.Optional(CONF_LAST4): TextSelector(),
            vol.Optional(CONF_PREVIOUS_LAST4): TextSelector(),
            vol.Optional(CONF_NICKNAME): TextSelector(),
            vol.Optional(CONF_COLOR): SelectSelector(
                SelectSelectorConfig(
                    options=list(CARD_COLORS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="card_color",
                )
            ),
            vol.Optional(CONF_ANNUAL_FEE): TextSelector(),
            vol.Optional(CONF_NOTES): TextSelector(),
        }
        if conditional:
            schema[vol.Optional(CONF_ENABLED_CONDITIONAL)] = SelectSelector(
                SelectSelectorConfig(
                    options=conditional, multiple=True, mode=SelectSelectorMode.LIST
                )
            )
        if benefits:
            schema[vol.Optional(CONF_NOT_APPLICABLE)] = SelectSelector(
                SelectSelectorConfig(options=benefits, multiple=True, mode=SelectSelectorMode.LIST)
            )
        if include_close:
            schema[vol.Optional(CONF_CLOSE_DATE)] = TextSelector()
        return vol.Schema(schema)

    def _validate_details(self, user_input: dict[str, Any], role: Role) -> dict[str, str]:
        errors: dict[str, str] = {}
        last4 = (user_input.get(CONF_LAST4) or "").strip()
        if last4 and not LAST4_RE.match(last4):
            errors[CONF_LAST4] = "invalid_last4"
        previous = _split_last4(user_input.get(CONF_PREVIOUS_LAST4))
        if previous is None:
            errors[CONF_PREVIOUS_LAST4] = "invalid_last4"
        else:
            user_input[CONF_PREVIOUS_LAST4] = previous
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
        for key in (
            CONF_OPEN_DATE,
            CONF_CLOSE_DATE,
            CONF_LAST4,
            CONF_NICKNAME,
            CONF_NOTES,
            CONF_COLOR,
        ):
            val = user_input.get(key)
            out[key] = (str(val).strip() or None) if val is not None else None
        fee = user_input.get(CONF_FEE_MONTH)
        out[CONF_FEE_MONTH] = int(fee) if fee else None
        af = user_input.get(CONF_ANNUAL_FEE)
        out[CONF_ANNUAL_FEE] = float(af) if af not in (None, "") else None
        prev = user_input.get(CONF_PREVIOUS_LAST4)
        out[CONF_PREVIOUS_LAST4] = list(prev) if isinstance(prev, list) else []
        out[CONF_ENABLED_CONDITIONAL] = list(user_input.get(CONF_ENABLED_CONDITIONAL) or [])
        out[CONF_NOT_APPLICABLE] = list(user_input.get(CONF_NOT_APPLICABLE) or [])
        return out

    async def _title_for(self, data: dict[str, Any]) -> str:
        if data.get(CONF_NICKNAME):
            return data[CONF_NICKNAME]
        catalog = await self._catalog_or_load()
        product = catalog.get(data[CONF_PRODUCT_ID])
        owner = next((o.title for o in self._owners() if o.subentry_id == data[CONF_OWNER_ID]), "?")
        name = product.name if product else data[CONF_PRODUCT_ID]
        suffix = f" | {data[CONF_LAST4]}" if data.get(CONF_LAST4) else ""
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
        catalog = await self._catalog_or_load()
        options = self._conditional_options(self._data[CONF_PRODUCT_ID], role)
        return self.async_show_form(
            step_id="details",
            data_schema=self._details_schema(
                include_close=False,
                conditional=options,
                benefits=self._benefit_options(self._data[CONF_PRODUCT_ID], role),
            ),
            errors=errors,
            description_placeholders={
                "conditions": _conditions_text(catalog.get(self._data[CONF_PRODUCT_ID]), role)
            },
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
                CONF_COLOR,
                CONF_ANNUAL_FEE,
                CONF_NOTES,
                CONF_CLOSE_DATE,
                CONF_PREVIOUS_LAST4,
            )
            and v is not None
        }
        if CONF_PREVIOUS_LAST4 in current:
            current[CONF_PREVIOUS_LAST4] = ", ".join(current[CONF_PREVIOUS_LAST4])
        if CONF_FEE_MONTH in current:
            current[CONF_FEE_MONTH] = str(current[CONF_FEE_MONTH])
        if CONF_ANNUAL_FEE in current:
            current[CONF_ANNUAL_FEE] = str(current[CONF_ANNUAL_FEE])
        catalog = await self._catalog_or_load()
        product = catalog.get(subentry.data.get(CONF_PRODUCT_ID, ""))
        options = self._conditional_options(subentry.data.get(CONF_PRODUCT_ID, ""), role)
        if subentry.data.get(CONF_ENABLED_CONDITIONAL):
            current[CONF_ENABLED_CONDITIONAL] = list(subentry.data[CONF_ENABLED_CONDITIONAL])
        if subentry.data.get(CONF_NOT_APPLICABLE):
            current[CONF_NOT_APPLICABLE] = list(subentry.data[CONF_NOT_APPLICABLE])
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                self._details_schema(
                    include_close=True,
                    conditional=options,
                    benefits=self._benefit_options(subentry.data.get(CONF_PRODUCT_ID, ""), role),
                ),
                current,
            ),
            errors=errors,
            description_placeholders={"conditions": _conditions_text(product, role)},
        )


class ImportSubentryFlow(ConfigSubentryFlow):
    """Bulk import from pasted CSV. Creates owner/card subentries, never one of its own."""

    async def _read_upload(self, file_id: str) -> str:
        def _read() -> str:
            with process_uploaded_file(self.hass, file_id) as path:
                raw = path.read_bytes()
            for enc in ("utf-8-sig", "utf-16", "cp1252"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")

        return await self.hass.async_add_executor_job(_read)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        text = ""
        if user_input is not None:
            text = (user_input.get(ATTR_CSV) or "").strip()
            if user_input.get(ATTR_FILE):
                text = await self._read_upload(user_input[ATTR_FILE])
            if not text.strip():
                errors["base"] = "nothing_to_import"
        if user_input is not None and not errors:
            entry = self._get_entry()
            catalog = await async_get_catalog(self.hass)
            self.hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
            try:
                result = await async_import_cards(self.hass, entry, catalog, text)
            finally:
                self.hass.data[DOMAIN][DATA_IMPORTING] = False
            if result.created_owners or result.created_cards:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

            def _fmt(items: list[str]) -> str:
                return "\n".join(f"- {i}" for i in items) if items else "- none"

            return self.async_abort(
                reason="import_complete",
                description_placeholders={
                    "owners": _fmt(result.created_owners),
                    "cards": _fmt(result.created_cards),
                    "skipped": _fmt(result.skipped),
                    "errors": _fmt(result.errors),
                },
            )
        schema = vol.Schema(
            {
                vol.Optional(ATTR_FILE): FileSelector(
                    FileSelectorConfig(accept=".csv,.xlsx,text/csv")
                ),
                vol.Optional(ATTR_CSV): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


async def _read_uploaded_text(hass, file_id: str) -> tuple[str, str | None]:
    """Return (text, original filename) for an uploaded file."""

    def _read() -> tuple[str, str | None]:
        with process_uploaded_file(hass, file_id) as path:
            raw = path.read_bytes()
            name = path.name
        return decode_statement(raw, name), name

    return await hass.async_add_executor_job(_read)


NEW_CARD = "__new__"
ALL_CARDS = "__all__"


class ImportStatementSubentryFlow(ConfigSubentryFlow):
    """Read a raw issuer CSV export, creating the card if it is not set up yet.

    Statement upload is meant to be the default way in: nobody can track fifteen
    credits on four cadences by hand, so the flow will build the card from the file
    rather than making the user configure it first.
    """

    def __init__(self) -> None:
        super().__init__()
        self._parsed: ParsedStatement | None = None
        self._catalog: Catalog | None = None
        self._file_hash = ""
        self._filename: str | None = None

    async def _catalog_or_load(self) -> Catalog:
        if self._catalog is None:
            self._catalog = await async_get_catalog(self.hass)
        return self._catalog

    def _owners(self) -> list[ConfigSubentry]:
        return [
            s for s in self._get_entry().subentries.values() if s.subentry_type == SUBENTRY_OWNER
        ]

    def _cards_for_issuer(self, issuer: str, catalog: Catalog) -> list[ConfigSubentry]:
        return cards_for_issuer(self._get_entry(), catalog, issuer)

    def _statement_last4(self) -> str | None:
        """The card number to assume, when the file names exactly one."""
        assert self._parsed is not None
        if len(self._parsed.last4s) == 1:
            return next(iter(self._parsed.last4s))
        return self._parsed.filename_last4

    # ---- step 1: the file
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get(ATTR_FILE):
            text, name = await _read_uploaded_text(self.hass, user_input[ATTR_FILE])
            try:
                self._parsed = parse_statement(text, name)
            except ValueError:
                errors["base"] = "unrecognised_statement"
            if not errors:
                self._file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                self._filename = name
                return await self.async_step_card()
        elif user_input is not None:
            errors["base"] = "nothing_to_import"
        schema = vol.Schema(
            {
                vol.Required(ATTR_FILE): FileSelector(
                    FileSelectorConfig(accept=".csv,.xlsx,text/csv")
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    def _summary(self) -> dict[str, str]:
        assert self._parsed is not None
        parsed = self._parsed
        fee = latest_fee(parsed)
        rng = parsed.date_range
        return {
            "issuer": parsed.issuer,
            "rows": str(len(parsed.rows)),
            "range": f"{rng[0].isoformat()} to {rng[1].isoformat()}" if rng else "no dated rows",
            "credits": str(len(parsed.credit_rows)),
            "fee": f"{fee.amount:.2f} on {fee.date.isoformat()}" if fee else "none found",
            "cards": ", ".join(sorted(parsed.last4s)) or "not stated in the file",
        }

    # ---- step 2: which card, or a new one
    async def async_step_card(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        assert self._parsed is not None
        parsed = self._parsed
        catalog = await self._catalog_or_load()
        # Cards from the detected issuer, else every card, so a mislabelled issuer still
        # lets the user pick rather than forcing a duplicate card.
        cards = self._cards_for_issuer(parsed.issuer, catalog) or [
            s for s in self._get_entry().subentries.values() if s.subentry_type == SUBENTRY_CARD
        ]

        if user_input is not None:
            if user_input[ATTR_CARD] == NEW_CARD:
                return await self.async_step_new_card()
            if user_input[ATTR_CARD] == ALL_CARDS:
                return await self._apply_all(bool(user_input.get(ATTR_APPLY_FEE, True)))
            return await self._apply(
                user_input[ATTR_CARD],
                bool(user_input.get(ATTR_APPLY_FEE, True)),
                adopt=set(user_input.get(ATTR_ADOPT_LAST4) or ()),
            )

        if not cards:
            return await self.async_step_new_card()

        hints = set(parsed.last4s)
        if parsed.filename_last4:
            hints.add(parsed.filename_last4)
        default = next(
            (c.subentry_id for c in cards if c.data.get(CONF_LAST4) in hints), cards[0].subentry_id
        )
        options = [SelectOptionDict(value=c.subentry_id, label=c.title) for c in cards]
        options.append(SelectOptionDict(value=NEW_CARD, label="Add a new card from this statement"))
        # A household's Chase export covers every Chase card at once; offer one pass.
        covered = cards_in_statement(self._get_entry(), parsed)
        if len(covered) > 1:
            titles = ", ".join(c.title for c in covered)
            options.insert(
                0,
                SelectOptionDict(
                    value=ALL_CARDS, label=f"Every card in this file ({len(covered)}: {titles})"
                ),
            )
            default = ALL_CARDS
        schema = vol.Schema(
            {
                vol.Required(ATTR_CARD, default=default): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(ATTR_APPLY_FEE, default=True): BooleanSelector(),
            }
        )
        if unassigned := self._unassigned_last4s(catalog):
            schema = schema.extend(
                {
                    vol.Optional(ATTR_ADOPT_LAST4): SelectSelector(
                        SelectSelectorConfig(
                            options=sorted(unassigned),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            )
        return self.async_show_form(
            step_id="card", data_schema=schema, description_placeholders=self._summary()
        )

    def _unassigned_last4s(self, catalog: Catalog) -> set[str]:
        """Numbers in the file that belong to no configured card.

        Usually a replaced card: same account, new number after loss or theft.
        """
        assert self._parsed is not None
        taken: set[str] = set()
        for s in self._get_entry().subentries.values():
            if s.subentry_type != SUBENTRY_CARD:
                continue
            if s.data.get(CONF_LAST4):
                taken.add(s.data[CONF_LAST4])
            taken.update(s.data.get(CONF_PREVIOUS_LAST4) or [])
        return self._parsed.last4s - taken

    # ---- step 3 (optional): build the card from the statement
    async def async_step_new_card(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        assert self._parsed is not None
        parsed = self._parsed
        catalog = await self._catalog_or_load()
        owners = self._owners()
        if not owners:
            return self.async_abort(reason="no_owners")
        products = catalog.by_issuer().get(parsed.issuer) or sorted(
            catalog.products.values(), key=lambda p: (p.issuer_name, p.name)
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            last4 = (user_input.get(CONF_LAST4) or "").strip()
            if last4 and not LAST4_RE.match(last4):
                errors[CONF_LAST4] = "invalid_last4"
            if not user_input.get(CONF_FEE_MONTH):
                errors[CONF_FEE_MONTH] = "need_anniversary"
            if not errors:
                card_id = await self._create_card(user_input)
                return await self._apply(card_id, apply_fee=True)

        fee = latest_fee(parsed)
        defaults: dict[str, Any] = {}
        if fee is not None:
            defaults[CONF_FEE_MONTH] = str(fee.date.month)
        if (l4 := self._statement_last4()) is not None:
            defaults[CONF_LAST4] = l4
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
                vol.Required(CONF_PRODUCT_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=p.id, label=f"{p.issuer_name} {p.name}")
                            for p in products
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_FEE_MONTH): _month_selector(),
                vol.Optional(CONF_LAST4): TextSelector(),
                vol.Optional(CONF_NICKNAME): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="new_card",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
            errors=errors,
            description_placeholders=self._summary(),
        )

    async def _create_card(self, user_input: dict[str, Any]) -> str:
        """Add the held-card subentry, then reload so its entities exist."""
        assert self._parsed is not None
        entry = self._get_entry()
        catalog = await self._catalog_or_load()
        product = catalog.get(user_input[CONF_PRODUCT_ID])
        owner = next(
            (o for o in self._owners() if o.subentry_id == user_input[CONF_OWNER_ID]), None
        )
        last4 = (user_input.get(CONF_LAST4) or "").strip() or None
        nickname = (user_input.get(CONF_NICKNAME) or "").strip() or None

        fee = latest_fee(self._parsed.for_last4(last4))
        annual_fee = None
        if fee is not None and product is not None and fee.amount != product.annual_fee:
            annual_fee = fee.amount

        name = product.name if product else user_input[CONF_PRODUCT_ID]
        suffix = f" | {last4}" if last4 else ""
        title = nickname or f"{name} ({owner.title if owner else '?'}{suffix})"
        data = {
            CONF_OWNER_ID: user_input[CONF_OWNER_ID],
            CONF_PRODUCT_ID: user_input[CONF_PRODUCT_ID],
            CONF_ROLE: str(Role.PRIMARY),
            CONF_PARENT_CARD_ID: None,
            CONF_OPEN_DATE: None,
            CONF_FEE_MONTH: int(user_input[CONF_FEE_MONTH]),
            CONF_LAST4: last4,
            CONF_NICKNAME: nickname,
            CONF_NOTES: None,
            CONF_ANNUAL_FEE: annual_fee,
            CONF_ENABLED_CONDITIONAL: [],
            CONF_NOT_APPLICABLE: [],
            CONF_PREVIOUS_LAST4: [],
            CONF_COLOR: None,
            CONF_CLOSE_DATE: None,
        }
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_CARD,
            title=title,
            unique_id=None,
        )
        # Suppress the listener-driven reload so we can await one deterministically:
        # the coordinator must know about the card before usage is recorded.
        self.hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
        try:
            self.hass.config_entries.async_add_subentry(entry, subentry)
        finally:
            self.hass.data[DOMAIN][DATA_IMPORTING] = False
        await self.hass.config_entries.async_reload(entry.entry_id)
        self._created_title = title
        return subentry.subentry_id

    async def _adopt_numbers(self, card_id: str, adopt: set[str]) -> None:
        """Record extra card numbers as earlier versions of this account."""
        entry = self._get_entry()
        sub = entry.subentries[card_id]
        merged = sorted(set(sub.data.get(CONF_PREVIOUS_LAST4) or []) | adopt)
        self.hass.data.setdefault(DOMAIN, {})[DATA_IMPORTING] = True
        try:
            self.hass.config_entries.async_update_subentry(
                entry, sub, data={**sub.data, CONF_PREVIOUS_LAST4: merged}
            )
        finally:
            self.hass.data[DOMAIN][DATA_IMPORTING] = False
        await self.hass.config_entries.async_reload(entry.entry_id)

    # ---- apply
    async def _apply(
        self, card_id: str, apply_fee: bool, adopt: set[str] | None = None
    ) -> SubentryFlowResult:
        assert self._parsed is not None
        entry = self._get_entry()
        adopt = adopt or set()
        if adopt:
            await self._adopt_numbers(card_id, adopt)
        card = entry.runtime_data.card(card_id)
        others = self._parsed.other_last4s(card.all_last4)
        result = apply_statement(
            self.hass,
            entry,
            card_id,
            self._parsed,
            file_hash=self._file_hash,
            filename=self._filename,
            apply_fee=apply_fee,
        )
        return self._finish([result], others, adopt)

    async def _apply_all(self, apply_fee: bool) -> SubentryFlowResult:
        """One pass over every configured card the file covers."""
        assert self._parsed is not None
        entry = self._get_entry()
        covered = cards_in_statement(entry, self._parsed)
        known: set[str] = set()
        for sub in covered:
            known |= subentry_last4s(sub)
        results = [
            apply_statement(
                self.hass,
                entry,
                sub.subentry_id,
                self._parsed,
                file_hash=self._file_hash,
                filename=self._filename,
                apply_fee=apply_fee,
            )
            for sub in covered
        ]
        return self._finish(results, self._parsed.last4s - known, set())

    def _finish(self, results, others: set[str], adopt: set[str]) -> SubentryFlowResult:
        placeholders = summarise(results, others)
        note = ""
        if adopt:
            note += (
                f"Also treating {', '.join(sorted(adopt))} as earlier numbers for this card.\n\n"
            )
        if getattr(self, "_created_title", None):
            note = f"Created the card **{self._created_title}** from this statement.\n\n"
        placeholders["note"] = note + placeholders["note"]
        return self.async_abort(reason="statement_complete", description_placeholders=placeholders)
