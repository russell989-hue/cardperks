# CardPerks handoff

State of the project as of 2026-09-06, written so someone new (or a future session)
can pick it up without the conversation that built it. Read this, then `TODO.md`.

## What it is

A Home Assistant custom integration (domain `cardperks`, HACS-shaped) that tracks
credit-card benefits so none go unused, plus a generated Lovelace dashboard. It runs
on Brian's HA OS box (Proxmox VM, address in `tools/secrets.env`, HA 2026.9.1, Python 3.14) and is
in daily use with nine cards across two owners.

The one idea everything else follows: **everything is dollars over a trailing twelve
months, and statements are the source of truth.** A $25 monthly credit is $300 a year;
what matters is how much was captured, how much was forfeited when a period closed,
how much is still open, and how much is unknown because no statement covered that
month. Manual dollar boxes exist as the fallback, not the main flow.

## Where things are

| Path | What |
| --- | --- |
| `custom_components/cardperks/` | the integration |
| `custom_components/cardperks/catalog/*.json` | shipped card products, one file per issuer (Chase, Amex, Capital One) |
| `tests/` | 90 pytest tests (one is the privacy guard), fixture catalog under `tests/fixtures/catalog/` |
| `tools/` | deploy script, dashboard generators, and the live push tools |
| `tools/secrets.env` | untracked: the HA box address and SSH key for deploys |
| `.github/workflows/validate.yml` | hassfest on every push |
| `brands/` | icon PNGs for a home-assistant/brands PR, rendered by `tools/make_brand.py`; the same files ship in `custom_components/cardperks/brand/`, which HA 2026.3+ serves directly |
| `docs/CATALOG.md` | catalog field reference and contribution rules |
| `custom_components/cardperks/panel.py` | serves the catalog page at `/cardperks/catalog` (rendered live by `catalog_page.py`, overrides included, no auth: catalog data only) and the fonts at `/cardperks/static/`; the dashboard's Catalog view is an iframe over it |
| `TODO.md` | one list of what is next and why |
| `docs/CATALOG-LOG.md` | dated record of catalog changes |
| `blueprints/automation/cardperks/` | the statement drop-folder blueprint; deploy.sh ships it. On Brian's box Folder Watcher watches `/config/cardperks/statements` and the automation `cardperks_statement_drop_folder` runs the import |
| `README.md` | user-facing install and usage |

The repo is `C:\Users\BrianRussell\dev\cardperks`, branch `main`, with a private
remote at https://github.com/russell989-hue/cardperks (GitHub CLI signed in as
`russell989-hue`; push with plain `git push`). Every commit message explains the why.

CI runs hassfest on every push (`.github/workflows/validate.yml`); the HACS
validation job is deliberately left out until the integration is ready to publish.

**Privacy rule for the repo:** no real last-four digits, dates or LAN addresses in
tracked files or in history. Examples and tests use made-up numbers; the deploy
target lives in the untracked `tools/secrets.env` (see `secrets.env.example`); statement
exports, `.storage` and `data/` are ignored. The history was rewritten once with
git-filter-repo to enforce this, so do not merge anything from an old clone.

## The model, in one screen

- **Config entry** "Home" with subentries: `owner`, `held_card`, `import` (CSV of
  cards), `statement` (a raw issuer export). `held_card_id == subentry_id`. A card's
  colour, open date, fee month, last four (and previous last fours for a replaced
  card), fee override, enabled conditional benefits and not-applicable benefits all
  live on its subentry; edit them in the card's form.
- **State** in `.storage/cardperks.state` (`store.py`, `StateDocument`): open benefit
  instances, closed history, perk values, card status, statement coverage, import
  receipts, and the set of already-applied statement lines.
- **Statement path**: `statements.py` parses; `statement_apply.py` applies a parsed file to
  one card (records usage, coverage, receipt, fee) and is shared by the upload flow and the
  `import_statement` service. The flow offers "Every card in this file" for a multi-card
  export. `add_statement_match` writes a pattern into the override folder via
  `catalog_write.py` and reloads.
- **Pure modules**: `periods.py` (calendar vs cardmember-year periods), `rollover.py`
  (idempotent daily close-and-open at 00:05, backfills gaps as `unknown`),
  `statements.py` (Chase, Amex, Capital One parsers; `statement_match` regexes from
  the catalog map credit lines to benefits), `importer.py`, `catalog.py` (schema),
  `models.py` (`Benefit`, `HeldCard`, `Totals`).
- **Benefit types**: `statement_credit` (a capped amount per period), `perk` and
  `insurance` (no issuer amount; the user assigns a value), `earning` (points, no
  dollars), `rebate` (a share of spend returned with no cap: nothing to check off,
  nothing to forfeit, a year of it is worth whatever it returned).
- **Shared perks**: a perk with `shared_key` (Priority Pass, Centurion, hotel status, cell
  phone protection, airline bags) is valued once for the household on a "Household"
  device number (`shared_<key>_value`, kind `shared_value`) and split equally between the
  active cards that carry it; the per-card `_value` number does not exist for it. The
  coordinator folds the split into `effective_perk_values`, which rollover, summaries and
  the snapshot all use.
- **Ledger** (`doc.ledger`, a `_ledger` sensor per card): every dollar logged against a
  benefit with date, amount, source (statement or manual) and note; corrections are
  negative lines. Seeded once from `imported_refs`.
- **Calendar** (`calendar.household_calendar`, on the Household device): fee dates, a review
  reminder 30 days before each, big credits closing with money still on them, statuses
  entered by hand lapsing, and the household's own reminders (`doc.reminders`, added from
  the calendar UI). `blueprints/automation/cardperks/daily_digest.yaml` turns it into one
  notification a day; on Brian's box `automation.cardperks_daily_digest` sends to his phone
  at 09:00.
- **Elite status**: `grants_status` on a catalog benefit makes a status sensor per cardholder
  while the card is held; the `status` subentry is for status earned outright, picking a
  program and tier from `programs/*.json` when the program is in the catalog.
- **Card status** picklist: active, frozen (kept but excluded from totals), cancelled
  (also hidden from the overview).
- **Entities per benefit**: `_used` number (the dollar box), `_remaining`, `_status`,
  `_expires` sensors, a mark-used button, and `_value` number for perks. Per card:
  fee due, unused value, net value, annual value, captured, forfeited, capture rate,
  statement coverage, fee-within-45-days, statement-upload-overdue (with a matching
  repair issue), and the status select. Per owner: rollups.
- **Every entity carries** `kind` (its translation key), `card`, `card_id`, `color`,
  `card_status`, and benefit entities add `benefit`. Dashboards filter on these and
  never on entity ids, which follow whatever an entity was called when created.
- **Benefit names** carry their cadence when not yearly: "Uber Cash (monthly)".

## Dev loop

Home Assistant only supports Linux, but the tests run natively on Windows with
three shims. One-time setup from the repo root (`uv` and Python 3.14 are on the
Office machine; any 3.13+ works):

```bash
uv venv -p 3.14 .venv-win
uv pip install -p .venv-win/Scripts/python.exe -r requirements_test.txt
.venv-win/Scripts/python.exe tools/setup_windows_tests.py .venv-win
```

`tools/setup_windows_tests.py` writes `fcntl`, `resource` and a `sitecustomize`
socketpair shim into the venv (see its docstring). They never ship; CI on Linux runs
the real harness. Then:

```bash
.venv-win/Scripts/python.exe -m pytest -q -p no:sugar tests
.venv-win/Scripts/ruff.exe check . && .venv-win/Scripts/ruff.exe format .
```

The venv pins `pytest-homeassistant-custom-component==0.13.363` (HA 2026.9.0).
`pytest-sugar` must be disabled (`-p no:sugar`). WSL2 with the same requirements works
too if you have it; nothing depends on it.

## Deploy

`bash tools/deploy.sh` tars the integration over SSH (host and key from `tools/secrets.env`,
no scp on HA OS) and reloads the config entry.

**Any change to a `.py` file needs `bash tools/deploy.sh --restart`.** A reload reuses
the modules already imported, so new code silently is not running and setup can fail
against new data files. Core is back in about 35 seconds; poll `/api/states` from the
SSH add-on for a marker the new code produces before pushing dashboards.

## Dashboards

Dashboard `dashboard-cardperks`, four tabs and nine hidden card subviews, every view on
the `CardPerks` theme (`themes/cardperks.yaml`, shipped by deploy.sh; fonts served by the
integration and wired in via `extra_module_url` in configuration.yaml):

- **My Cards Dashboard** (path `cardperks`): At a glance (four household figures: left to
  use, captured this year, missed this year, the next big credit to close), Cards (one tile
  per active card from a template, tap opens the subview), Big ticket items, Expiring within
  30 days, the Left-to-use ring.
- **Analysis** (path `money`): Was it worth it? (a verdict per card from its newest complete cardmember year),
  By card money bars, Net value gauges, Annual fees, Where the big dollars went (ring plus
  the forfeited list), By year (a table per card).
- **Upkeep**: Statements (overdue, then coverage), Log a credit, What perks are worth to you.
- **Catalog**: an iframe over the page the integration serves.
- One subview per card, reached from the tiles.

Everything is generated; nothing on the dashboard is hand-built any more (Brian's original
first section is in the 2026-09-06 backup under `/config/cardperks/backups/` and the
OneDrive `dashboard-backups/` folder). Rebuild and push with the tools below; a whole view
is replaced by path, so regenerate and push rather than editing in the UI.

Generators (run on Windows, output JSON):

- `tools/cp_full.py` runs on the box and dumps the live card map (ids, titles,
  colours, per-card entity ids, status select, perk entities) as JSON.
- `tools/build_sections.py outdir/` writes each shared section; `tools/build_views.py
  views_main.json` assembles the three top-level views from them.
- `tools/build_card_views.py cards.json views.json nav.json` writes the subviews, the
  Catalog view and the navigation section (the nav is no longer pushed; it lives in
  Brian's section). The "Dollars left by benefit" section is generated but not on the
  Overview; Brian removed it, so do not append it.
- `tools/lovelace.py` is the shared library: headings, notes, Mushroom rows, entity
  rows labelled benefit-first, gauges, the ring, the stacked money bars, expanders,
  two-column sections.

Push tools (run inside the SSH add-on, `$SUPERVISOR_TOKEN`, Supervisor websocket):

- `append_section.py <dash> <view> <section.json> [--was "<old heading>"]` replaces a
  section by its heading (looking inside expanders), or appends.
- `push_dashboard.py <dash> _ views.json` replaces whole views by path;
  `reorder_views.py <dash> path...` orders the tabs; `set_view_theme.py` sets a view's theme.
- `remove_section.py`, `prune_views.py` (drops subviews whose path is no longer
  generated, e.g. after a card rename).
- All of them back the config up to `/tmp/cardperks_dashboard_backup_<ts>.json` first
  and **carry over layout set in the UI** (section column spans, per-card grid
  options at the same position) unless the generator sets its own.
- `verify_templates.py` renders every template in the generated files through the
  websocket in **strict** mode. Run it before pushing; the markdown card is strict and
  errors on an attribute a sensor lacks, which is why every template uses `.get()`.
- `dump_dashboard.py <dash>` lists views, sections and card types.
- `recolor_card.py <colour> "<title part>"` drives a card's own reconfigure flow
  through the REST API to change one field without touching the rest.

How the visuals work, since none of it is a chart library:

- Colour flows from the `color` attribute: Mushroom `icon_color` templates, card-mod
  on entity rows (`--paper-item-icon-color`), gauges via `--info-color` and
  `--gauge-color`.
- The ring is a Markdown card whose inner `ha-markdown` element card-mod paints as a
  conic gradient computed by a template; slices per card, shades per benefit via
  `color-mix`. The size is forced on `ha-markdown` because HA sizes the card frame.
- The stacked money bars are Markdown cards with a `::before` linear gradient: green
  captured, red forfeited, grey unknown, dim track still open. One scheme everywhere;
  card colours are identity, not meaning.
- Entity-row lists are auto-entities `template` filters that build rows named
  "<benefit> used: <card>", because HA 2026.9 always prefixes the device name and the
  order cannot be changed integration-side. `peek_rows` shows three and folds the
  rest behind an expander whose title counts what is hidden.
- The auto-entities visual editor shows attribute rules but marks integration and
  wildcard entity-id rules "Unknown"; that is why filters are attribute-only.

HACS resources in use: auto-entities, Mushroom, card-mod, expander-card. Also
installed but unused: apexcharts-card, mini-graph-card, button-card, layout-card.

## Working agreements with Brian

- Dollar boxes, not picklists; benefit before card in every label; coloured icons,
  never emoji or markdown-table dots; colour is set once in the card form and is not
  selectable on dashboards.
- Amex Platinum is light grey on purpose (the card is silver). Do not flag it.
- He edits the dashboard by hand between pushes. Never replace his first section;
  keep layout he sets.
- The in-app browser cannot reach his LAN. Verify with the strict template check and
  the dump tool, then ask him for a screenshot.
- "Don't make any edits yet" means exactly that.
- The catalog page (`/cardperks/catalog`) is served without a login and marks which
  products the household holds. Brian decided (2026-09-06) that LAN access is an acceptable
  boundary for that fact. Do not add auth or strip the owned-cards marking.
- Nothing personal in the repo, even though it is private: no card numbers, no
  dates, no addresses. Put such values in `tools/secrets.env` or keep them out.

## Known rough edges

- Gauge titles can clip at three per row on narrower screens.
- The shipped catalog (15 products) was checked against issuer pages on 2026-09-06; only the
  two Amex business cards remain `needs_verification`. Details in the backlog.
