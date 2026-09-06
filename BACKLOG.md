# CardPerks backlog

Ideas and deferred work, most valuable first within each group. Phase numbers refer
to the roadmap in the scope document. `HANDOFF.md` describes the current state.

## Guiding principle: statement upload is the default path

Nobody can track this by hand. A single Amex Platinum has fifteen credits on four
different cadences; a household of ten cards is hundreds of periods a year. Manual
check-off is the fallback for things statements cannot show, not the main flow.

Everything should be built so the normal loop is **download a CSV, upload it, done**.
Done so far: upload creates the card, prefilled from the file; rows are scoped to the
chosen card's last four (and its former numbers after a replacement); each upload
records the months it covers and a receipt; uncapped rebates are recorded as their
own benefit type. Done: upload creates the card; multi-card exports apply to every card in one pass;
`cardperks.import_statement` takes a file path (point a `folder_watcher` automation at
`/config/cardperks/statements/` for a drop folder); `cardperks.add_statement_match`
writes a missing pattern into the override folder; forfeited consults coverage; a repair
and binary sensor nag when uploads fall behind.

Remaining:

1. **A shipped drop-folder automation.** A blueprint that wires `folder_watcher` to
   `import_statement`, so the user does not have to write it.

## Small things

- **Navigation tiles from a template.** The Cards tiles now live in Brian's hand-built
  section and are static, so a new card needs a tile added by hand. An auto-entities
  template over the `unused_value` sensors with `tap_action: navigate` to
  `/dashboard-cardperks/{{ card | slugify }}` would make them appear by themselves.
- **Gauges at two per row** if titles keep clipping on narrower screens.
- **Cadence tags are English-only**, like everything in `strings.json`. Fine until
  the integration is published.

## Next up

### Historical backfill: was this card ever worth it?

Upload several years of statements and answer the question the yearly fee actually
poses. The plumbing is most of the way there: statement import writes into `history`
for closed periods, it is idempotent, and the trailing-twelve-month totals read from
that same history. What is missing is scale and honesty about gaps.

- **Multi-year import in one pass.** A five-year export should walk every period it
  covers, opening and closing history records as it goes.
- **Reconstruct periods before the card was tracked.** Backfill has to synthesise the
  period grid backwards from the open date or fee month.
- **Cardmember-year totals, not just trailing twelve months.** Fee charged, credits
  captured before the next fee, net; a per-year table.
- **Say what is unknown.** Periods with no evidence stay `unknown` rather than
  forfeited (the live year already works this way: a closed statement-credit period
  is forfeited only when statements cover every month of it).
- **Catalog history: settled 2026-09-06.** Historical mode reports what statements prove
  and nothing else: fee paid, credits captured, net, per cardmember year. It does not say
  what was available in past years, so it never reports past forfeited dollars. The
  alternative, `valid_from` / `valid_to` on every benefit, would mean curating every
  issuer's past terms from memory, which breaks the catalog's official-sources rule
  (issuer pages do not publish history). "Was this card worth it" needs only captured
  minus fee, and that is answerable from the statements alone. If a year's evidence is
  partial, the year is marked as such.

### Loyalty status tracker (airlines, hotels, rental cars)

Track elite status separately from cards, because status both comes from cards and
unlocks card benefits. Brian's United Premier Gold is what makes the United Club All
Access authorized-user passes real, and that link is only a note in a conditional
benefit's `condition` text today.

- A third subentry type, `status`, one per program per owner: program, tier,
  qualifying period end, how it was earned.
- Entities: current tier, expiry, days remaining, progress toward the next tier where
  thresholds are published.
- Catalog: `grants_status` on a benefit (holding the card confers Hilton Gold) and
  `requires_status` on a conditional benefit so qualification is evaluated instead of
  hand-toggled.
- Renewal reminders reuse the 45-day fee pattern.

Open: which programs ship versus user-defined; whether qualifying-activity tracking
(segments, nights, dollars) is worth the data entry.

## Later

- **Bank sync (Phase 5).** Optional SimpleFIN component writing into the same history
  documents. Statement import already covers most of the value with no third party.
- **More issuers for statement import.** Citi, Bank of America, Barclays. One parser
  function per issuer plus `statement_match` patterns in the catalog.
- **Best-card lookup (Phase 3).** Which card to use for a purchase, from earning rates
  and rotating categories. Rotating activations are already stored.
- **Sidebar panel (Phase 2).** Only worth it for the published version; the Lovelace
  dashboard covers it.
- **Publish (Phase 4).** hassfest and HACS validation in CI, brands PR, screenshots,
  catalog contribution guide, a `dashboards/` folder with the generated JSON so other
  installs can import the same layout.
- **A real chart library.** apexcharts-card is installed; the CSS ring and bars could
  become its donut and bar charts if richer interaction is ever wanted. The CSS
  versions need no extra resource and follow card colours live, so this is optional.

## Catalog verification

All seven shipped products were checked against the issuer pages on 2026-09-06 and
`needs_verification` cleared; `last_verified` carries the date. What changed:

- Amex Platinum: CLEAR credit is $219; Uber Cash gets a $20 December bonus (noted, still
  $15 a month in the catalog); Delta Sky Club visits added as a perk.
- Venture X: additional cardholders no longer get Capital One Lounge access free ($125 a
  year each); Hertz status is Gold Plus, not President's Circle; cell phone protection added.
- Sapphire Reserve: $250 select-hotels credit for 2026 only and IHG Platinum status added;
  notes on the split credits and their end dates.
- Ink Business Preferred: sign-up bonus is 100,000 points; $10 a month DoorDash credit added.
- Southwest Plus: fee is $99 (a card with a $69 statement line keeps its own override);
  EarlyBird credits replaced by standard seat selection under assigned seating; flight
  discount code, Companion Pass boost, 25% inflight rebate, DoorDash and Instacart credits,
  and free first bag added.
- United Explorer and Club: the 2025 refresh. Hotel, JSX and Avis/Budget credits are per
  anniversary year at the new amounts ($100/$100/$50 Explorer, $200/$200/$100 Club);
  Instacart is $10 and $20 a month; Club rideshare is $12 a month with $18 in December;
  Explorer gains the $100 TravelBank credit after $10,000 spend (conditional); Club gains
  award-flight discounts. Source URLs updated to the current Chase pages.

Still open: statement_match patterns for the new credits are guesses until a statement
shows the real line (use `cardperks.add_statement_match` when one appears); Southwest
sign-up bonus not restated on the page; Equinox credit on the Platinum not listed on the
Amex page this pass and left in place.

Verified from statements earlier: Chase fee months and amounts for every Chase card, Amex
Platinum fee date and the Resy credit's quarterly cadence, Venture X fee month and amount,
United inflight/club 25% rebate lines on the Club card. United Club authorized users
confirmed to get no club access of their own.
