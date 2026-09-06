# CardPerks backlog

Ideas and deferred work. Phase numbers refer to the roadmap in the scope document.

## Next up

### Loyalty status tracker (airlines, hotels, rental cars)

Track elite status separately from cards, because status both **comes from** cards and
**unlocks** card benefits. Brian's United Premier Gold is what makes the United Club
All Access authorized-user passes real, and that link is currently only a note in a
conditional benefit's `condition` text.

Sketch:

- A third subentry type, `status`, one per program per owner: program (United MileagePlus,
  Marriott Bonvoy, Hertz, and so on), tier, qualifying period end, and how it was earned
  (spend, card benefit, match, or challenge).
- Entities per status: current tier, expiry date, days remaining, and for programs with
  published thresholds, progress toward the next tier.
- Catalog additions: `grants_status` on a benefit (the card confers Hilton Gold, say) so
  holding the card auto-creates the status entry, and `requires_status` on a conditional
  benefit so qualification is evaluated instead of hand-toggled.
- Renewal reminders reuse the existing 45-day fee pattern.

Open questions: which programs ship in the catalog versus being user-defined; whether
qualifying-activity tracking (segments, nights, dollars) is in scope or too much data
entry to be worth it.

## Later

- **Bank sync (Phase 5).** Optional SimpleFIN component writing into the same history
  documents. Statement import already covers most of the value with no third party.
- **More issuers for statement import.** Citi, Bank of America, Barclays. The parser is
  one function per issuer plus `statement_match` patterns in the catalog.
- **Best-card lookup (Phase 3).** Which card to use for a purchase, from earning rates
  and rotating categories. Rotating activations are already stored.
- **Sidebar panel (Phase 2).** A Lit panel over the websocket API. The Lovelace dashboard
  covers this for now, so this is only worth it for the published version.
- **Publish (Phase 4).** hassfest and HACS validation in CI, brands PR, screenshots,
  catalog contribution guide.

## Catalog verification

Every shipped product is flagged `needs_verification` and listed in Repairs. Verified so
far from statements: Chase fee months and amounts for 1001, 1111, 1002, 1003, 5678, 1234;
Amex Platinum fee date and the Resy credit's quarterly cadence; Capital One Venture X fee
month and amount. United Club authorized users confirmed to get no club access of their own.
