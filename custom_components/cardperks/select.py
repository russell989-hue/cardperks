"""The one thing that genuinely is a picklist: whether a card is being tracked.

Dollar amounts are typed, not chosen from a list. Colour is set once in the card form.
"""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SUBENTRY_CARD, CardStatus, LedgerWindow
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import CardEntity, CardPerksEntity, household_device_info
from .helpers import card_from_subentry
from .models import HeldCard


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CardPerksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_CARD:
            continue
        async_add_entities(
            [CardStatusSelect(coordinator, card_from_subentry(sub))],
            config_subentry_id=sub.subentry_id,
        )
    async_add_entities([LedgerWindowSelect(coordinator)])


class CardStatusSelect(CardEntity, SelectEntity):
    """Active, frozen or cancelled."""

    _attr_translation_key = "card_status"
    _attr_options: ClassVar[list[str]] = [str(s) for s in CardStatus]
    _attr_icon = "mdi:credit-card-settings-outline"

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator, card)
        self._attr_unique_id = f"{card.id}_status"

    @property
    def current_option(self) -> str | None:
        card = self.card
        return str(card.status) if card else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.card_attributes)

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_card_status(self.held_card_id, option)


class LedgerWindowSelect(CardPerksEntity, SelectEntity):
    """How far back the ledgers look: one picker, every card page follows it."""

    _attr_translation_key = "ledger_window"
    _attr_options: ClassVar[list[str]] = [str(w) for w in LedgerWindow]
    _attr_icon = "mdi:calendar-range"

    def __init__(self, coordinator: CardPerksCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "ledger_window"
        self._attr_device_info = household_device_info()

    @property
    def current_option(self) -> str:
        return self.coordinator.doc.ledger_window

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lo, hi = self.coordinator.window_bounds(
            self.coordinator.doc.ledger_window, self.coordinator.data.today
        )
        return {"kind": self.translation_key, "from": lo, "to": hi}

    async def async_select_option(self, option: str) -> None:
        self.coordinator.set_ledger_window(option)
