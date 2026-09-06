"""Base entities for CardPerks."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import CardPerksCoordinator
from .devices import card_identifier, owner_identifier
from .models import Benefit, BenefitInstance, HeldCard, Owner


def card_device_info(coordinator: CardPerksCoordinator, card: HeldCard) -> DeviceInfo:
    # The device itself (with manufacturer, model, via_device_id) is created in devices.py
    # before platforms load; entities only need to point at it.
    return DeviceInfo(identifiers={card_identifier(card.id)})


def owner_device_info(owner: Owner) -> DeviceInfo:
    return DeviceInfo(identifiers={owner_identifier(owner.id)})


class CardPerksEntity(CoordinatorEntity[CardPerksCoordinator]):
    _attr_has_entity_name = True


class CardEntity(CardPerksEntity):
    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator)
        self.held_card_id = card.id
        self._attr_device_info = card_device_info(coordinator, card)

    @property
    def card(self) -> HeldCard | None:
        return self.coordinator.data.cards.get(self.held_card_id)

    @property
    def summary(self):
        return self.coordinator.data.card_summaries.get(self.held_card_id)


class BenefitEntity(CardEntity):
    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard, benefit: Benefit) -> None:
        super().__init__(coordinator, card)
        self.benefit_id = benefit.id
        self.benefit = benefit
        self._attr_translation_placeholders = {"benefit": benefit.name}

    @property
    def instance(self) -> BenefitInstance | None:
        return self.coordinator.data.instances.get(f"{self.held_card_id}:{self.benefit_id}")

    @property
    def available(self) -> bool:
        return super().available and self.instance is not None


class OwnerEntity(CardPerksEntity):
    def __init__(self, coordinator: CardPerksCoordinator, owner: Owner) -> None:
        super().__init__(coordinator)
        self.owner_id = owner.id
        self._attr_device_info = owner_device_info(owner)

    @property
    def summary(self):
        return self.coordinator.data.owner_summaries.get(self.owner_id)

    @property
    def available(self) -> bool:
        return super().available and self.summary is not None
