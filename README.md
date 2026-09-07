# CardPerks

> **Read this first.**
>
> **This project was written entirely by an AI.** The author is not a software developer.
> Every line of code, test, catalog entry and document in this repository was produced by
> Claude (Anthropic) working from the author's descriptions of what he wanted, what is
> sometimes called "vibe coding". A human reviewed the behaviour, not the code.
>
> **Use it entirely at your own risk.** It is provided "as is", without warranty of any
> kind, and the author accepts no liability for anything that follows from using it: a
> credit you thought was tracked and was not, a fee you paid because a date was wrong, a
> number that did not add up, data that was lost, or anything else. Check the issuer's own
> terms before relying on any figure here.
>
> **Nothing in this project is financial advice.** The catalog is a best effort at
> transcribing issuer marketing pages on a given date and will be wrong or out of date in
> places. Dollar values, "net value", "capture rate" and the rest are arithmetic on what
> you and your statements put in, not a recommendation to hold, use, apply for or cancel
> any card. The author is not a financial adviser and has no relationship with any issuer.

A Home Assistant integration that makes sure every credit-card benefit in your household gets used. Each held card becomes a device, each benefit becomes entities you can see, automate on, and check off.

**Status: Phase 1 (backend + entities). No custom panel yet.**

## What you get

Everything is measured in dollars. A $25 monthly credit is $300 a year, and what matters
is how much of that you actually captured, not whether this month is ticked off. Periods
that close unused are **forfeited**, tracked separately from what is still capturable.
Once you import statements, a statement credit only counts as forfeited when a statement
covered every month of its period; a month nobody has a statement for is **unknown**.

Per benefit on each card:

- `number.<card>_<benefit>_used`, the dollars captured this period. This is the input: type what you spent.
- `sensor.<card>_<benefit>_remaining`, dollars left this period.
- `sensor.<card>_<benefit>_status`, derived from the amount (`unused`, `partial`, `used`, `n_a`), for automations.
- `sensor.<card>_<benefit>_expires`, the date the current period ends.
- `button.<card>_<benefit>_mark_used` for one tap.
- `number.<card>_<benefit>_value` for perks with no issuer amount, so lounge access is worth what it is worth to you.
- `number.household_<perk>_value_all_cards` for a perk several cards share (Priority Pass): one value for the household, split equally between the cards that carry it.

Per card: annual credit value, captured and forfeited over the trailing 12 months, capture
rate, annual fee due date, unused value this period, net value (captured minus fee), and a
binary sensor that turns on 45 days before the fee posts, and another that turns on
(with a Repairs entry) when a card you track by statement is more than a month behind.

Per owner: the same three dollar totals, plus unused credits, counts expiring within 7 and
30 days, and a 5/24 count.

Benefits that do not apply to you are marked on the card and drop out of every total.

Statements can also arrive by file: `cardperks.import_statement` reads an export already
on the box (for example dropped into `config/cardperks/statements/`), CSV or Excel, and applies it to
every card it covers, and `cardperks.add_statement_match` teaches the catalog a credit
line that went unmatched, without editing JSON.

For a drop folder, set up the Folder Watcher integration on `config/cardperks/statements/`
and create an automation from the **CardPerks statement drop folder** blueprint
(`blueprints/automation/cardperks/`): every CSV dropped there is imported and a
notification reports what was recorded.

Services: `cardperks.mark_used`, `cardperks.reset_benefit`, `cardperks.add_sub_spend`, `cardperks.set_perk_value`, `cardperks.activate_rotating_category`.

A daily job at 00:05 local time closes expired periods into history and opens the next ones. It catches up correctly after downtime.

## Install

1. Copy `custom_components/cardperks` into your `config/custom_components/` folder (or add this repo as a custom repository in HACS).
2. Restart Home Assistant.
3. Settings, Devices & services, Add integration, **CardPerks**. Name the household and the first owner.
4. On the CardPerks integration page use **Add owner** and **Add card** for everything else. Authorized-user cards are linked to the primary card they belong to.

## Importing

On the CardPerks integration page:

- **Import cards from CSV** takes a `.csv` file or pasted rows with at least `owner` and `product` columns (plus optional `issuer`, `role`, `parent_owner`, `open_date`, `fee_month`, `last4`, `nickname`, `annual_fee`, `notes`). Existing cards are skipped.
- **Import statement** takes a raw Chase Activity export, American Express CSV download, or Capital One transaction download, exactly as downloaded. It reads the annual fee line to set the fee month and actual fee, and records labelled credit lines (`TRAVEL CREDIT $300/YEAR`, `Platinum Resy Credit`, and so on) as benefit usage in the period they belong to. Re-importing the same file changes nothing. Credit lines that match no benefit are listed so you can add a `statement_match` pattern to the catalog. Uncapped rebates, such as 25% back on United inflight purchases, are recorded the same way; they count as captured and can never be forfeited, since there is no pool to lose.

Both run entirely on your Home Assistant box.

## Catalog

Card products live in `custom_components/cardperks/catalog/*.json`, one file per issuer, checked against the issuer page linked in each product's `source_url` (the date is in `last_verified`). Anything still drafted is flagged `needs_verification` and listed in Home Assistant's Repairs panel. The field reference and contribution rules are in [docs/CATALOG.md](docs/CATALOG.md).

To correct or extend the catalog without editing the integration, drop JSON files in `config/cardperks/catalog/`. A product with an existing `id` replaces the shipped one entirely. A broken file is skipped and reported in Repairs.

## Privacy

No user data leaves your machine. Card holdings, owners, last-four digits, usage history, and valuations live only in Home Assistant's `.storage/cardperks.state` and are covered by your normal backups. There is no telemetry, no cloud account, and no network access in this version. Diagnostics downloads redact last-four digits, nicknames, owner names, and notes.

Two boundaries to know about. The catalog page at `/cardperks/catalog` is served without a login so it can sit inside a dashboard view; it shows the shipped catalog plus which products your household holds (never owners, last-fours or amounts), so anyone on your network can see which cards you have. The values you type on that page ("My value", cents per point) stay in that browser's local storage and never reach Home Assistant. Statements you drop in `config/cardperks/statements/` are read locally and never uploaded anywhere.

## Development

Home Assistant only runs on Linux. On Windows use WSL2.

```bash
python3.14 -m venv ~/venvs/cardperks && source ~/venvs/cardperks/bin/activate
pip install -U pip wheel && pip install -r requirements_test.txt
pytest -q
ruff check .
```

`tools/deploy.sh` copies the integration to a Home Assistant OS box over SSH and reloads it; `tools/deploy.sh --restart` restarts Core instead. Any change to a `.py` file needs the restart, since a reload keeps the modules already imported.

## Dashboards

`dashboards/views_main.json` is the generated set of top-level views, free of household data, ready to import; see `dashboards/README.md`. The Lovelace dashboard is generated: `tools/build_sections.py` and `tools/build_card_views.py` write JSON from the live entity map, and the push tools in `tools/` apply it over the Supervisor websocket while keeping layout set in the UI. `HANDOFF.md` explains the structure, the visual tricks, and the working agreements.
