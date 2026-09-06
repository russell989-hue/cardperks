# CardPerks handoff

State of the project as of 2026-09-06, written so someone new (or a future session)
can pick it up without the conversation that built it. Read this, then `BACKLOG.md`.

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
| `BACKLOG.md` | what is deferred and why |
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
- **Pure modules**: `periods.py` (calendar vs cardmember-year periods), `rollover.py`
  (idempotent daily close-and-open at 00:05, backfills gaps as `unknown`),
  `statements.py` (Chase, Amex, Capital One parsers; `statement_match` regexes from
  the catalog map credit lines to benefits), `importer.py`, `catalog.py` (schema),
  `models.py` (`Benefit`, `HeldCard`, `Totals`).
- **Benefit types**: `statement_credit` (a capped amount per period), `perk` and
  `insurance` (no issuer amount; the user assigns a value), `earning` (points, no
  dollars), `rebate` (a share of spend returned with no cap: nothing to check off,
  nothing to forfeit, a year of it is worth whatever it returned).
- **Card status** picklist: active, frozen (kept but excluded from totals), cancelled
  (also hidden from the overview).
- **Entities per benefit**: `_used` number (the dollar box), `_remaining`, `_status`,
  `_expires` sensors, a mark-used button, and `_value` number for perks. Per card:
  fee due, unused value, net value, annual value, captured, forfeited, capture rate,
  statement coverage, fee-within-45-days, and the status select. Per owner: rollups.
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

Dashboard `dashboard-cardperks`. The Overview (view path `cardperks`) has a hand-built
first section owned by Brian ("Unused Credits and Benefits", which also holds the
per-card navigation tiles), followed by generated sections. Nine generated subviews,
one per card, reached from those tiles.

Generators (run on Windows, output JSON):

- `tools/cp_full.py` runs on the box and dumps the live card map (ids, titles,
  colours, per-card entity ids, status select, perk entities) as JSON.
- `tools/build_sections.py outdir/` writes each Overview section.
- `tools/build_card_views.py cards.json views.json nav.json` writes the subviews and
  the navigation section (the nav is no longer pushed; it lives in Brian's section).
- `tools/lovelace.py` is the shared library: headings, notes, Mushroom rows, entity
  rows labelled benefit-first, gauges, the ring, the stacked money bars, expanders,
  two-column sections.

Push tools (run inside the SSH add-on, `$SUPERVISOR_TOKEN`, Supervisor websocket):

- `append_section.py <dash> <view> <section.json> [--was "<old heading>"]` replaces a
  section by its heading (looking inside expanders), or appends.
- `push_dashboard.py <dash> _ views.json` replaces whole views by path.
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
- Nothing personal in the repo, even though it is private: no card numbers, no
  dates, no addresses. Put such values in `tools/secrets.env` or keep them out.

## Known rough edges

- A benefit whose catalog name already ends in parentheses gets a second pair from
  the cadence tag: "Hotel credit (FHR / The Hotel Collection) (every 6 months)".
- Gauge titles can clip at three per row on narrower screens.
- The shipped catalog is drafted from general knowledge and flagged
  `needs_verification`; Repairs lists it. Verified so far is noted in the backlog.
- Statement import is one card per pass; a multi-card Chase export is uploaded once
  per card (rows are scoped by last four, so nothing is misattributed).
