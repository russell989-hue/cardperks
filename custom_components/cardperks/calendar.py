"""The CardPerks calendar: fee dates, review reminders, statuses lapsing, your own notes.

One calendar for the household. Fee dates and the 30-day review reminders are computed
from the cards, statuses from the status tracker, and anything else (cancel a
subscription before its introductory rate ends) is added from the calendar UI and kept
in the state document.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import BIG_TICKET_MIN, FEE_WARNING_DAYS, REVIEW_DAYS_BEFORE_FEE, BenefitStatus
from .coordinator import CardPerksConfigEntry, CardPerksCoordinator
from .entity import CardPerksEntity, household_device_info
from .periods import add_months, next_fee_date


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CardPerksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([CardPerksCalendar(entry.runtime_data)])


def _as_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        return dt_util.as_local(value).date()
    return value


class CardPerksCalendar(CardPerksEntity, CalendarEntity):
    """All-day events, computed on demand, plus the reminders the household adds."""

    _attr_translation_key = "calendar"
    _attr_icon = "mdi:calendar-star"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, coordinator: CardPerksCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = "cardperks_calendar"
        self._attr_device_info = household_device_info()

    # ------------------------------------------------------------------ events

    def _events(self, start: date, end: date) -> list[CalendarEvent]:
        """Every event between two dates (end exclusive), soonest first."""
        data = self.coordinator.data
        out: list[CalendarEvent] = []

        def add(day: date, summary: str, description: str, uid: str) -> None:
            if start <= day < end:
                out.append(
                    CalendarEvent(
                        start=day,
                        end=day + timedelta(days=1),
                        summary=summary,
                        description=description,
                        uid=uid,
                    )
                )

        for card in data.cards.values():
            summary = data.card_summaries.get(card.id)
            if summary is None or not card.is_active(data.today):
                continue
            fee = summary.annual_fee
            anniv = next_fee_date(data.today, card.open_date, card.fee_month)
            if anniv is None:
                continue
            # Walk anniversaries back and forward to cover the window.
            day = anniv
            while day >= start:
                day = add_months(day, -12)
            while day < end:
                if day >= data.today - timedelta(days=366):
                    add(
                        day,
                        f"${fee:,.0f} annual fee: {card.title}",
                        "The annual fee posts today. Net over the trailing year on the CardPerks "
                        "dashboard is what the card returned against it.",
                        f"fee-{card.id}-{day.isoformat()}",
                    )
                    review = day - timedelta(days=REVIEW_DAYS_BEFORE_FEE)
                    add(
                        review,
                        f"Review {card.title} before its ${fee:,.0f} fee",
                        f"The fee posts on {day.isoformat()}, in {REVIEW_DAYS_BEFORE_FEE} days. "
                        "Decide whether the card still earns its keep: keep, downgrade or cancel. "
                        "Check its captured, forfeited and net figures on the Money tab first.",
                        f"review-{card.id}-{day.isoformat()}",
                    )
                day = add_months(day, 12)

        # Big credits still unused: the day each one closes.
        for inst in data.instances.values():
            card = data.cards.get(inst.held_card_id)
            if card is None or not card.is_active(data.today) or not inst.period_end:
                continue
            if inst.status not in (BenefitStatus.UNUSED, BenefitStatus.PARTIAL):
                continue
            remaining = max((inst.amount or 0.0) - inst.amount_used, 0.0)
            if remaining < BIG_TICKET_MIN:
                continue
            product = data.catalog.get(card.product_id)
            benefit = product.benefit(inst.benefit_id) if product else None
            name = benefit.label if benefit else inst.benefit_id
            closes = date.fromisoformat(inst.period_end)
            add(
                closes,
                f"Use ${remaining:,.0f} {name} by today: {card.title}",
                "Last day of this credit's period. Whatever is unused after today is forfeited.",
                f"credit-{card.id}-{inst.benefit_id}-{inst.period_end}",
            )

        for sid, status in data.statuses.items():
            if status.valid_through is None:
                continue
            add(
                status.valid_through,
                f"{status.program} {status.tier} lapses ({status.source})",
                "Elite status ends today unless it was re-earned or the card that grants it is "
                "still held.",
                f"status-{sid}",
            )

        for rem in self.coordinator.doc.reminders:
            day = date.fromisoformat(rem["date"])
            if start <= day < end:
                out.append(
                    CalendarEvent(
                        start=day,
                        end=day + timedelta(days=1),
                        summary=rem["summary"],
                        description=rem.get("description"),
                        uid=rem["uid"],
                    )
                )

        out.sort(key=lambda e: (e.start, e.summary))
        return out

    @property
    def event(self) -> CalendarEvent | None:
        today = self.coordinator.data.today
        upcoming = self._events(today, today + timedelta(days=400))
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self._events(_as_date(start_date), _as_date(end_date))

    # ------------------------------------------------------------------ the household's own reminders

    async def async_create_event(self, **kwargs: Any) -> None:
        start = _as_date(kwargs["dtstart"])
        self.coordinator.add_reminder(
            start, kwargs.get("summary") or "Reminder", kwargs.get("description")
        )

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        self.coordinator.remove_reminder(uid)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "review_days_before_fee": REVIEW_DAYS_BEFORE_FEE,
            "fee_warning_days": FEE_WARNING_DAYS,
        }
