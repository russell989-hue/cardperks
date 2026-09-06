# CardPerks to-do

One list, most valuable first within each group. `HANDOFF.md` describes the current
state; `docs/CATALOG.md` is the catalog reference and `docs/CATALOG-LOG.md` the dated
record of catalog changes. `[~]` = partly done. Updated 2026-09-06.

## Guiding principle: statement upload is the default path

Nobody can track this by hand. A single Amex Platinum has fifteen credits on four
cadences; a household of ten cards is hundreds of periods a year. Manual check-off is
the fallback for things statements cannot show, not the main flow. Everything is built
so the normal loop is **download a CSV, drop it, done**, and every number says what it
is based on: captured, forfeited, unknown, still open.

## Now

- [x] **Drop-folder blueprint.** `blueprints/automation/cardperks/statement_drop_folder.yaml`
      wires Folder Watcher to `cardperks.import_statement`; deploy ships it and creates
      `config/cardperks/statements/`. Files under `config/cardperks/` need no allowlist entry.
- [x] **Navigation tiles from a template.** The Cards section on the Overview is an
      auto-entities template over the `unused_value` sensors; a new card gets a tile by itself.
- [ ] **Dashboard, round three.** The Overview, Money and Upkeep split is in (2026-09-06).
      Judge it from a screenshot, then: heading subtitles, a type chip on the "All benefits"
      list via Mushroom badges, and whether the At-a-glance tiles want to be bigger.
- [ ] Gauges at two per row if titles keep clipping on narrower screens.
- [ ] Amex Business Platinum and Business Gold: read the official pages in a browser and
      clear `needs_verification`.
- [ ] Statement wording for the credits added on 2026-09-06 is guessed; use
      `cardperks.add_statement_match` as real lines show up, then move the pattern into
      the shipped catalog.

## Next

### Historical backfill: was this card ever worth it?

Upload several years of statements and answer the question the fee actually poses. The
plumbing is mostly there: import writes closed periods into `history`, it is idempotent,
and the trailing-year totals read from that history. Missing is scale and honesty about
gaps. Decision (2026-09-06): historical mode reports what statements prove, fee paid,
captured and net per cardmember year, and never claims what was available in past
years, because curating old issuer terms from memory breaks the official-sources rule.

- [ ] Multi-year import in one pass, walking every period the file covers.
- [ ] Reconstruct the period grid backwards from the open date or fee month.
- [ ] Per-cardmember-year table: fee charged, captured before the next fee, net; a year
      with partial evidence is marked as such.

### Loyalty status tracker (airlines, hotels, rental cars)

Status both comes from cards and unlocks card benefits; United Premier Gold is what
makes the Club All Access authorized-user passes real, and that link is a note today.

- [ ] A `status` subentry per program per owner: program, tier, qualifying period end,
      how it was earned.
- [ ] Entities: current tier, expiry, days remaining, progress where thresholds are public.
- [ ] Catalog: `grants_status` on a benefit (holding the card confers Hilton Gold) and
      `requires_status` on a conditional benefit, so qualification is evaluated instead of
      hand-toggled. Renewal reminders reuse the 45-day fee pattern.
- [ ] Decide which programs ship versus user-defined, and whether qualifying-activity
      tracking (segments, nights, dollars) is worth the data entry.

### Money views

- [ ] Best-card lookup for a purchase, from earning rates and rotating categories
      (activations are already stored).
- [ ] Sign-up bonus tracker and 5/24 view (the entities exist).
- [ ] Authorized-user comparison view.
- [ ] Default point valuations (MR, UR, Capital One, United, Southwest) or "use community
      rates"; only the sign-up bonus tracker needs them.

## Later

- [ ] More issuers for statement import: Citi, Bank of America, Barclays. One parser branch
      per issuer plus `statement_match` patterns.
- [ ] Optional SimpleFIN bank-sync component writing into the same history documents.
      Statement import covers most of the value with no third party.
- [ ] apexcharts-card versions of the ring and bars, only if richer interaction is wanted.
      The CSS versions need no extra resource and follow card colours live.
- [ ] Sidebar panel (Lit/TS) only if a published version must not depend on Mushroom,
      card-mod, auto-entities and expander-card.
- [ ] Cadence tags and every string translatable; English-only today.

## Publish

- [ ] HACS validation job in CI (needs the brands assets merged and a public repo).
- [ ] Open the home-assistant/brands PR; assets are ready in `brands/cardperks/`.
- [ ] README with screenshots and a privacy statement; a `dashboards/` folder with the
      generated JSON so other installs can import the layout.
- [ ] Notification blueprints (expiring credits, fee due, statement overdue).
- [ ] Re-run the privacy audit on the whole history before flipping the repo public.
- [ ] Tag a release; test a clean install as a custom HACS repository.
- [ ] Branch protection on `main` if CI should gate merges.

## Keeping the Android option open

A standalone, paid Android app would rebuild every screen and all storage, but the
core (periods, rollover, statement parsing and matching, shared perks, coverage rules)
and the catalog carry over as the spec. Two cheap things keep that possible:

- [x] `tests/test_core_is_portable.py` forbids Home Assistant imports in the pure modules
      and keeps them importing only each other.
- [ ] Record catalog changes as dated entries in `docs/CATALOG-LOG.md` (started
      2026-09-06) so a future app can ship "what changed" and the history question has a
      real answer as a side effect.

## Done

- 2026-09-06: private GitHub repo with hassfest CI and a privacy guard; native Windows
  test loop; forfeited consults coverage; statement-overdue reminder; every card in a
  multi-card export in one pass; import by file path; add a match pattern from the
  import result; import receipts keyed per file and card; fee lines newest-wins with a
  catalog-mismatch repair; catalog verified against issuer pages and grown to 15
  products; contribution guide; history question settled; catalog page in the dashboard
  with an owned-cards toggle; CardPerks theme with self-hosted fonts; shared perks valued
  once for the household; logo.
- Earlier: household entry with owner, card, CSV and statement subentries; benefit engine
  with calendar and cardmember-year periods and daily rollover; entities per benefit,
  card and owner; rebate type; card status; replaced-card numbers; conditional and
  not-applicable benefits; dashboards generated from templates with layout-preserving
  push tools and strict template verification.
