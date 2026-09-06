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
    """Anything belonging to one held card."""

    def __init__(self, coordinator: CardPerksCoordinator, card: HeldCard) -> None:
        super().__init__(coordinator)
        self.held_card_id = card.id
        self._attr_device_info = card_device_info(coordinator, card)

    @property
    def card(self) -> HeldCard | None:
        return self.coordinator.data.cards.get(self.held_card_id)

    @property
    def card_attributes(self) -> dict[str, str | None]:
        """Identity of the card, repeated on its entities so a dashboard can group and colour.

        `kind` names what the entity is (fee_due, benefit_remaining, perk_value, ...) so a
        dashboard filter can say `attributes: {kind: fee_due}` instead of guessing at
        entity ids, which follow whatever the entity was called when it was created.
        """
        card = self.card
        return {
            "kind": self.translation_key,
            "card": card.title if card else None,
            "card_id": self.held_card_id,
            "color": self.coordinator.data.colors.get(self.held_card_id),
            "card_status": str(card.status) if card else None,
        }

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
    def owner_attributes(self) -> dict[str, str | None]:
        """Identity of the owner, so a dashboard can find these without guessing entity ids."""
        owner = self.coordinator.data.owners.get(self.owner_id)
        return {
            "kind": self.translation_key,
            "owner": owner.name if owner else None,
            "owner_id": self.owner_id,
        }

    @property
    def summary(self):
        return self.coordinator.data.owner_summaries.get(self.owner_id)

    @property
    def available(self) -> bool:
        return super().available and self.summary is not None
