# CardPerks backlog

Ideas and deferred work. Phase numbers refer to the roadmap in the scope document.

## Guiding principle: statement upload is the default path

Nobody can track this by hand. A single Amex Platinum has fifteen credits on four
different cadences; a household of ten cards is hundreds of periods a year. Manual
check-off is the fallback for things statements cannot show, not the main flow.

Everything should be built so the normal loop is **download a CSV, upload it, done**.
Concrete gaps between that and today:

- ~~**Statement upload should create the card.**~~ Done: the flow offers "Add a new card
  from this statement", prefills last four and fee month from the file, and applies the
  credits in the same pass.
- **One file, many cards.** Partly done: rows are now scoped to the chosen card's last
  four, so a multi-card Chase export no longer misattributes credits, and the result says
  which other cards the file covers. Still manual: importing the same file once per card.
  Applying to every matching card in one pass is the remaining step.
- **A statement should be able to create several cards at once.** With the above, the
  first upload of a household's Chase export could stand up every card in it.
- **Repeat imports without ceremony.** A service that takes a file path so a user can
  automate it, and/or a watched folder such as `/config/cardperks/statements/`. Import is
  already idempotent, so re-running is safe by construction.
- **Close the matching gap in-product.** Unmatched credit lines are listed today but
  fixing one means hand-editing catalog JSON. Offer to write the pattern into a user
  override file straight from the import result.
- ~~**Say what a statement could not tell you.**~~ Done: each upload records the months
  it covers plus a receipt (file hash, issuer, row counts, what was applied), and a
  per-card coverage sensor lists covered and missing months. Still to do: feed coverage
  into the forfeited figure so an uncovered month counts as unknown rather than lost,
  and surface "no statement since" as a repair or reminder.

## Next up

### Historical backfill: was this card ever worth it?

Upload several years of statements and answer the question the yearly fee actually
poses. The plumbing is already most of the way there: statement import writes into
`history` for closed periods, it is idempotent, and the trailing-twelve-month totals
read from that same history. What is missing is scale and honesty about gaps.

What it needs:

- **Multi-year import in one pass.** Today a file is applied against the periods it
  overlaps; a five-year export should walk every period it covers, opening and closing
  history records as it goes rather than only touching the current one.
- **Reconstruct periods before the card was tracked.** Rollover only knows about periods
  since setup. Backfill has to synthesise the period grid backwards from the open date or
  fee month, so a 2022 credit lands in the 2022 period.
- **Cardmember-year totals, not just trailing twelve months.** The judgement is per fee
  paid: fee charged, credits captured before the next fee, net. A per-year table beats a
  single rolling number for this question.
- **Say what is unknown.** A statement proves a credit was used; nothing proves one was
  not, since an unlabelled purchase may have triggered it. Periods with no evidence stay
  `unknown` rather than counting as forfeited, and the report shows the three-way split.
  Without that the tool will confidently tell people they wasted money they did not.
- **Catalog history is the hard part.** The Sapphire Reserve's credits in 2022 were not
  the 2026 ones, and the fee was $550 not $795. Judging 2022 against today's catalog is
  wrong. This needs `valid_from` / `valid_to` on benefits, or an explicit decision to
  report only what the statements themselves show and skip the potential side.

That last point is the real design question, and it is worth settling before building:
either the catalog gains time-versioned benefits, or historical mode reports captured
dollars and fees paid only, and stays silent about what was available.

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
