# CardPerks

A Home Assistant integration that makes sure every credit-card benefit in your household gets used. Each held card becomes a device, each benefit becomes entities you can see, automate on, and check off.

**Status: Phase 1 (backend + entities). No custom panel yet.**

## What you get

Per benefit on each card:

- `select.<card>_<benefit>` with states `unused`, `partial`, `used`, `n_a`. Changing it is the check-off.
- `sensor.<card>_<benefit>_expires`, the date the current period ends, with amount, amount used, and period start as attributes.
- `button.<card>_<benefit>_mark_used` for one-tap dashboards and automations.

Per card: annual fee due date, unused value this period, net value over the trailing 12 months (credits used minus fee), and a binary sensor that turns on 45 days before the fee posts.

Per owner: unused credits in dollars, counts of benefits expiring within 7 and 30 days (with the list as an attribute), and a 5/24 count.

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
- **Import statement** takes a raw Chase Activity export, American Express CSV download, or Capital One transaction download, exactly as downloaded. It reads the annual fee line to set the fee month and actual fee, and records labelled credit lines (`TRAVEL CREDIT $300/YEAR`, `Platinum Resy Credit`, and so on) as benefit usage in the period they belong to. Re-importing the same file changes nothing. Credit lines that match no benefit are listed so you can add a `statement_match` pattern to the catalog.

Both run entirely on your Home Assistant box.

## Catalog

Card products live in `custom_components/cardperks/catalog/*.json`, one file per issuer. The shipped data for Chase, American Express, and Capital One was drafted from general knowledge and is flagged `needs_verification` until checked against the issuer pages linked in each product's `source_url`. Home Assistant's Repairs panel lists what still needs checking.

To correct or extend the catalog without editing the integration, drop JSON files in `config/cardperks/catalog/`. A product with an existing `id` replaces the shipped one entirely. A broken file is skipped and reported in Repairs.

## Privacy

No user data leaves your machine. Card holdings, owners, last-four digits, usage history, and valuations live only in Home Assistant's `.storage/cardperks.state` and are covered by your normal backups. There is no telemetry, no cloud account, and no network access in this version. Diagnostics downloads redact last-four digits, nicknames, owner names, and notes.

## Development

Home Assistant only runs on Linux. On Windows use WSL2.

```bash
python3.14 -m venv ~/venvs/cardperks && source ~/venvs/cardperks/bin/activate
pip install -U pip wheel && pip install -r requirements_test.txt
pytest -q
ruff check .
```

`tools/deploy.sh` copies the integration to a Home Assistant OS box over SSH and reloads it; `tools/deploy.sh --restart` restarts Core instead.
