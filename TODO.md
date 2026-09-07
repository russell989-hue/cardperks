# CardPerks to-do

One list, most valuable first within each group. `HANDOFF.md` describes the current
state; `docs/CATALOG.md` is the catalog reference and `docs/CATALOG-LOG.md` the dated
record of catalog changes. `[~]` = partly done. Updated 2026-09-07.

## Guiding principle: statement upload is the default path

Nobody can track this by hand. A single Amex Platinum has fifteen credits on four
cadences; a household of ten cards is hundreds of periods a year. Manual check-off is
the fallback for things statements cannot show, not the main flow. Everything is built
so the normal loop is **download a CSV, drop it, done**, and every number says what it
is based on: captured, forfeited, unknown, still open. Brian's rule (2026-09-06): a past
period nobody claimed was forfeited, even before tracking began.

## Waiting on Brian

- [ ] Uber Cash for 2025: the 2026 months were logged from Uber charges on the statements
      (rule: any month with a regular Uber charge used the whole credit). The 2025 files are
      no longer in the drop folder; re-drop them or say which 2025 months to log.
- [ ] Whether "unknown" (a month after tracking began with no statement) should also read
      red on the rings, or stay grey.
- [ ] Whether the two placeholder cards (Wells Fargo, Mattress Firm Synchrony) should be
      hidden from the Overview tiles, where they show as $0 left.
- [ ] Whether the Sign-up bonuses section should list only cards opened in the last year;
      today it lists every card, and every bonus window is long closed.
- [ ] Open dates for the two Inks (business cards, so 5/24 does not care; only the sign-up
      bonus rows do).
- [ ] Screenshots after the next round, for the dashboard polish items below.
- [ ] Whether tracking qualifying activity toward the next United tier (PQP, PQF) is worth
      the data entry. The next tier and its requirements already show on the status sensor.

## Now

- [ ] **Dashboard polish.** From the 2026-09-07 screenshots: ring cards on the card pages
      vary in height because long benefit names wrap to three lines (shorten the title or
      fix the card height); heading subtitles; a type chip on the "All benefits" list via
      Mushroom badges; whether the At-a-glance tiles want to be bigger.
- [ ] Gauges at two per row if titles keep clipping on narrower screens.
- [ ] Rings: decide whether perks and insurance belong in "Credits by period" or only
      statement credits and rebates (perks show today, marked-used or not).
- [ ] A household grid of the period rings, probably on the Analysis tab, once the card
      pages have settled.
- [ ] Statement wording for the credits added on 2026-09-06 is guessed; use
      `cardperks.add_statement_match` as real lines show up, then move the pattern into
      the shipped catalog. The United TravelBank credits (Avis/Budget, $10,000 spend) are
      the likeliest to need it: they pay into TravelBank, not the statement.

## Next

- [~] **An every-four-years cadence** anchored on the open date (2026-09-06): `every_four_years`
      builds four-year blocks from the open date and counts a quarter of the amount per year.
      Global Entry is still the $30-a-year shared perk, because a $120 credit on each of five
      cards would count five fees the household only pays once; switching it needs shared
      credits, or a household-level credit, first.
- [ ] Rotating categories in the best-card lookup (activations are stored; the ranking
      ignores them).
- [ ] Default point valuations (MR, UR, Capital One, United, Southwest) or "use community
      rates". The best-card lookup starts every currency at one cent and lets the viewer
      change it; the sign-up bonus tracker would need the same figures.
- [ ] A repair for an entered status about to lapse, following the 45-day fee pattern (the
      calendar and digest already carry it).

## Later

- [ ] More issuers for statement import: Citi, Bank of America, Barclays. One parser branch
      per issuer plus `statement_match` patterns.
- [ ] Optional SimpleFIN bank-sync component writing into the same history documents.
      Statement import covers most of the value with no third party.
- [ ] Sidebar panel (Lit/TS) only if a published version must not depend on Mushroom,
      card-mod, auto-entities and expander-card.
- [ ] Cadence tags and every string translatable; English-only today.
- [ ] Per-cardholder spending on a shared account is not possible from Chase's CSV (no
      cardholder column); revisit only if an export gains one.

## Publish

- [~] HACS validation job in CI (2026-09-06), advisory (`continue-on-error`) because
      hacs/action reads files through the GitHub API and gets nothing from a private repo.
- [~] README with screenshots and a privacy statement; a `dashboards/` folder with the
      generated JSON so other installs can import the layout. Privacy statement and
      `dashboards/views_main.json` done 2026-09-06; screenshots still wanted.
- [ ] Re-run the privacy audit on the whole history before flipping the repo public. Run on
      2026-09-06: no card numbers, tokens or personal data in any file version; the only
      finding is a work email as the git author on the earliest commits, which a public
      flip would need a history rewrite (or acceptance) to remove.
- [ ] Tag a release; test a clean install as a custom HACS repository.
- [ ] Branch protection on `main` if CI should gate merges.
- [ ] The home-assistant/brands PR only if installs older than HA 2026.3 matter; the icon
      ships in `custom_components/cardperks/brand/` and assets stay in `brands/cardperks/`.

## Keeping the Android option open

A standalone, paid Android app would rebuild every screen and all storage, but the
core (periods, rollover, statement parsing and matching, shared perks, coverage rules)
and the catalog carry over as the spec. Two cheap things keep that possible:

- [x] `tests/test_core_is_portable.py` forbids Home Assistant imports in the pure modules
      and keeps them importing only each other.
- [~] Record catalog changes as dated entries in `docs/CATALOG-LOG.md` (started
      2026-09-06) so a future app can ship "what changed" and the history question has a
      real answer as a side effect. Kept up so far.

## Decisions on record

- Historical mode reports what statements prove (fee paid, captured, net per cardmember
  year) and never claims what was available in past years (2026-09-06).
- LAN access is an acceptable boundary for the unauthenticated catalog page showing which
  products the household holds (2026-09-06).
- A past period nobody claimed counts as forfeited; blue-grey on a ring means part of the
  period's credit was used; in progress with nothing used is dim (2026-09-06).
- Uber Cash: a month with a regular Uber charge used the whole credit (2026-09-07).
- Open dates come from the credit report's account ages, to the month, matched to cards by
  fee month and Brian's memory of the order (2026-09-07).

## Done

- 2026-09-07: every card has an open date; a placeholder "Other card" product for cards
  whose benefits are not tracked (Wells Fargo, Mattress Firm Synchrony), so 5/24 is honest;
  `mark_used` with a date outside the open period records that period; Uber Cash logged
  for January to August 2026; Nick's authorized-user card dated.
- 2026-09-06 (evening): `requires_status` on conditional benefits; `every_four_years`
  cadence; earning rates for all 15 products on shared spend categories with a best-card
  lookup and an authorized-user table on the catalog page; the icon served from the
  integration's own `brand/` folder; sign-up bonuses and 5/24 on the Analysis tab; credits
  by period rings on every card page with a legend; tapping anything card-bound opens the
  card's subview; `dashboards/views_main.json`; README privacy boundaries; privacy audit of
  the whole history; HACS job in CI; hassfest green.
- 2026-09-06: private GitHub repo with hassfest CI and a privacy guard; native Windows
  test loop; forfeited consults coverage; statement-overdue reminder; every card in a
  multi-card export in one pass; import by file path; add a match pattern from the
  import result; import receipts keyed per file and card; fee lines newest-wins with a
  catalog-mismatch repair; catalog verified against issuer pages and grown to 15
  products; contribution guide; history question settled; catalog page in the dashboard
  with an owned-cards toggle; CardPerks theme with self-hosted fonts; shared perks valued
  once for the household; logo; drop-folder blueprint; navigation tiles from a template;
  was-it-worth-it verdicts and per-year table; loyalty status tracker with a program
  catalog; calendar and daily digest; ledger with a window picker; bottom navbar on card
  pages; "My value per year" on the catalog page.
- Earlier: household entry with owner, card, CSV and statement subentries; benefit engine
  with calendar and cardmember-year periods and daily rollover; entities per benefit,
  card and owner; rebate type; card status; replaced-card numbers; conditional and
  not-applicable benefits; dashboards generated from templates with layout-preserving
  push tools and strict template verification.
