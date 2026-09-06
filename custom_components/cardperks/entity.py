"""Base entities for CardPerks."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, Role
from .coordinator import CardPerksCoordinator
from .models import Benefit, BenefitInstance, HeldCard, Owner


def card_device_info(coordinator: CardPerksCoordinator, card: HeldCard) -> DeviceInfo:
    product = coordinator.catalog.get(card.product_id)
    info = DeviceInfo(
        identifiers={(DOMAIN, card.id)},
        name=card.title,
        manufacturer=product.issuer_name if product else None,
        model=product.name if product else card.product_id,
        serial_number=card.last4 or None,
        configuration_url=product.source_url if product else None,
    )
    if card.role is Role.AUTHORIZED_USER and card.parent_card_id:
        info["via_device"] = (DOMAIN, card.parent_card_id)
    return info


def owner_device_info(owner: Owner) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"owner:{owner.id}")},
        name=owner.name,
        manufacturer="CardPerks",
        model="Owner",
        entry_type=DeviceEntryType.SERVICE,
    )


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
