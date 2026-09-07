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
- [x] Every card-bound list, row and verdict on the dashboard opens that card's subview
      when tapped (2026-09-06); lists are template-built so the path comes from the title.
- [x] Credits by period (2026-09-06): one ring per benefit on each card page, a slice per
      period this year coloured by outcome, from the `periods` attribute every benefit
      status sensor carries. Next: a household grid of the same rings on the Overview,
      and a legend.
- [x] Amex Business Platinum and Business Gold verified from the official pages (2026-09-06).
- [ ] Statement wording for the credits added on 2026-09-06 is guessed; use
      `cardperks.add_statement_match` as real lines show up, then move the pattern into
      the shipped catalog.

## Next

- [x] **Was it worth it?** One verdict per card from its newest complete cardmember year
      (credits plus perks marked used, against the fee that year), at the top of the Money
      tab (2026-09-06). Fees are estimated from today's fee until statements covering the
      fee month are dropped in again; perks count only once marked used.
- [~] **An every-four-years cadence** anchored on the open date (2026-09-06): `every_four_years`
      builds four-year blocks from the open date and counts a quarter of the amount per year.
      Global Entry is still the $30-a-year shared perk, because a $120 credit on each of five
      cards would count five fees the household only pays once; switching it needs shared
      credits, or a household-level credit, first.

### Historical backfill: was this card ever worth it?

Upload several years of statements and answer the question the fee actually poses. The
plumbing is mostly there: import writes closed periods into `history`, it is idempotent,
and the trailing-year totals read from that history. Missing is scale and honesty about
gaps. Decision (2026-09-06): historical mode reports what statements prove, fee paid,
captured and net per cardmember year, and never claims what was available in past
years, because curating old issuer terms from memory breaks the official-sources rule.

- [x] Multi-year import in one pass: an export already writes every closed period it
      covers into history, so nothing was needed beyond keeping fee lines by date.
- [x] Reconstructing past periods is not needed under the decision above: past years report
      captured and fees, never what was available.
- [x] Per-cardmember-year table: fee seen, captured, net, months a statement covers; on the
      Money tab (2026-09-06). Fee lines are kept per date from now on; statements imported
      before that day show no fee for past years until they are dropped in again.

### Loyalty status tracker (airlines, hotels, rental cars)

Status both comes from cards and unlocks card benefits; United Premier Gold is what
makes the Club All Access authorized-user passes real, and that link is a note today.

- [x] A `status` subentry per program per owner (2026-09-06): owner, program, tier, valid
      through, how it was earned. Card-granted status comes from `grants_status` in the
      catalog and needs no entry.
- [x] A status sensor each: tier as state, source, valid through, days left, expiring-soon
      flag; listed on the Upkeep tab soonest to lapse first.
- [x] `requires_status` on a conditional benefit (2026-09-06): the benefit is on when the
      card's owner holds that tier or higher, valid today; the toggle still covers the spend
      route. United Club All Access passes carry it. Renewal reminders for entered statuses
      are on the calendar; a repair could follow the 45-day fee pattern.
- [ ] Progress toward the next tier where thresholds are public, and whether tracking
      qualifying activity (segments, nights, dollars) is worth the data entry.

### Money views

- [x] Best-card lookup for a purchase (2026-09-06): on the catalog page, over the
      shared spend categories, ranked by multiplier times the viewer's cents per point.
      Rotating categories (activations are stored) are not in the ranking yet.
- [x] Sign-up bonus tracker and 5/24 view on the Analysis tab (2026-09-06). Both need
      open dates on the cards to say anything: a bonus has no deadline and a card does
      not count toward 5/24 without one.
- [x] Authorized-user comparison on the catalog page (2026-09-06): AU fee, own lounge
      access, what the second card gets, held cards first.
- [ ] Default point valuations (MR, UR, Capital One, United, Southwest) or "use community
      rates". The best-card lookup starts every currency at one cent and lets the viewer
      change it; the sign-up bonus tracker would need the same figures.

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

- [~] HACS validation job in CI (2026-09-06), with the brands check ignored since the icon
      ships in the integration. Some checks may only pass once the repo is public.
- [x] Integration icon: shipped in `custom_components/cardperks/brand/` (2026-09-06), which
      Home Assistant 2026.3+ serves itself. The home-assistant/brands PR is only needed for
      installs older than that; assets stay ready in `brands/cardperks/`.
- [ ] README with screenshots and a privacy statement; a `dashboards/` folder with the
      generated JSON so other installs can import the layout.
- [x] Notification blueprint: the daily digest (big credits closing unused, statements
      overdue, today's fee, review, status and reminder events) (2026-09-06).
- [ ] Re-run the privacy audit on the whole history before flipping the repo public. Run on
      2026-09-06: no card numbers, tokens or personal data in any file version; the only
      finding is a work email as the git author on the earliest commits, which a public
      flip would need a history rewrite (or acceptance) to remove.
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
