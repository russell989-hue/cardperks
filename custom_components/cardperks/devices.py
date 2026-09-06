"""Create device registry entries for owners and cards before platforms load."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SUBENTRY_CARD, SUBENTRY_OWNER, Role
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .helpers import card_from_subentry, owner_from_subentry


def owner_identifier(owner_id: str) -> tuple[str, str]:
    return (DOMAIN, f"owner:{owner_id}")


def card_identifier(held_card_id: str) -> tuple[str, str]:
    return (DOMAIN, held_card_id)


@callback
def async_ensure_devices(
    hass: HomeAssistant, entry: CardPerksConfigEntry, coordinator: CardPerksCoordinator
) -> None:
    """Register one device per owner and per held card.

    Primary cards are created before authorized-user cards so the AU device can
    point at its parent through via_device_id.
    """
    registry = dr.async_get(hass)

    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_OWNER:
            continue
        owner = owner_from_subentry(sub)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=sub.subentry_id,
            identifiers={owner_identifier(owner.id)},
            name=owner.name,
            manufacturer="CardPerks",
            model="Owner",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    card_subs = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CARD]
    card_subs.sort(key=lambda s: Role(s.data.get("role", "primary")) is Role.AUTHORIZED_USER)
    for sub in card_subs:
        card = card_from_subentry(sub)
        product = coordinator.catalog.get(card.product_id)
        via_device_id = None
        if card.role is Role.AUTHORIZED_USER and card.parent_card_id:
            parent = registry.async_get_device_by_identifier(
                card_identifier(card.parent_card_id), entry.entry_id
            )
            via_device_id = parent.id if parent else None
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=sub.subentry_id,
            identifiers={card_identifier(card.id)},
            name=card.title,
            manufacturer=product.issuer_name if product else None,
            model=product.name if product else card.product_id,
            serial_number=card.last4 or None,
            configuration_url=product.source_url if product else None,
            via_device_id=via_device_id,
        )


@callback
def async_cleanup_entities(
    hass: HomeAssistant, entry: CardPerksConfigEntry, coordinator: CardPerksCoordinator
) -> int:
    """Drop registry entries for benefits that no longer exist for their card.

    Without this, correcting the catalog (a benefit removed, or no longer offered to
    authorized users) leaves entities behind that never become available again.
    """
    expected: set[str] = set()
    for owner_id in coordinator.owners:
        expected.update(
            f"owner_{owner_id}_{suffix}"
            for suffix in ("unused_credits", "expiring_7d", "expiring_30d", "5_24")
        )
    for card in coordinator.cards.values():
        expected.update(
            f"{card.id}_{suffix}"
            for suffix in ("fee_due", "unused_value", "net_value_12m", "fee_within_45d")
        )
        product = coordinator.catalog.get(card.product_id)
        if product is None:
            continue
        for benefit in product.benefits_for_role(card.role):
            expected.update(
                f"{card.id}_{benefit.id}_{suffix}"
                for suffix in ("status", "expires", "remaining", "mark_used")
            )

    registry = er.async_get(hass)
    stale = [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id not in expected
    ]
    for entity_id in stale:
        registry.async_remove(entity_id)
    return len(stale)
