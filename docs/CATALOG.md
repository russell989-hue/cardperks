# The card catalog

The catalog is what CardPerks knows about card products: the fee, every benefit, how
often each one comes round, and how it shows up on a statement. It ships as one JSON
file per issuer in `custom_components/cardperks/catalog/`, and you can correct or extend
it without touching the integration by dropping files into `config/cardperks/catalog/`.

This page is the field reference and the contribution rules. The schema itself lives in
`catalog.py`; if the two disagree, the code wins and this page has a bug.

## Rules

1. **Official sources only.** Every product carries a `source_url` pointing at the issuer's
   own page for the card. Blog posts and forums are fine for finding out that something
   changed; the catalog entry cites the issuer.
2. **Nothing personal, ever.** No card numbers, no open dates, no names, no statement
   exports, not even in examples. A `statement_match` pattern describes the issuer's
   wording of a credit line ("TRAVEL CREDIT"), never a specific transaction.
3. **Say what you checked.** Set `last_verified` to the date you compared the entry with
   the issuer page, and clear `needs_verification` only when the whole product was
   checked, not one benefit.
4. **Notes explain the fine print.** Enrollment, activation, split periods, end dates,
   what the credit is paid as (statement credit, TravelBank cash, in-app promo). If a
   benefit cannot appear on a statement, say so in `notes` so nobody waits for it.
5. **One product per card, not per pricing.** A card whose fee went up keeps one entry at
   the current fee; a holder still paying the old price sets a fee override on the card.

## File layout

```json
{
  "schema_version": 1,
  "issuer": "chase",
  "issuer_name": "Chase",
  "products": [ ... ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | no | Always `1` for now. |
| `issuer` | yes | Slug, `^[a-z0-9_]+$`. Also names the statement parser (`chase`, `amex`, `capital_one`). |
| `issuer_name` | yes | Display name. |
| `products` | yes | List of products, below. |

## Product

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `id` | yes | | Slug, `^[a-z0-9_]+$`, unique across every file. Convention: `<issuer>_<card>`. Never change an id once shipped; held cards reference it. |
| `name` | yes | | Card name as the issuer writes it, without the issuer ("Sapphire Reserve"). |
| `annual_fee` | yes | | Current fee in dollars. First-year waivers go in a benefit note, not here. |
| `currency` | no | `points` | What the card earns: `points`, `miles`, `cash`. |
| `default_point_value` | no | `0.01` | Dollars per point, used only for the sign-up bonus. |
| `reports_to_personal_credit` | no | `true` | Whether the card counts toward Chase's 5/24. Business cards from most issuers are `false`. |
| `last_verified` | yes | | ISO date of the last check against `source_url`. |
| `source_url` | yes | | The issuer's page for the card. |
| `needs_verification` | no | `false` | `true` while the entry is a draft. Listed in Repairs. |
| `benefits` | no | `[]` | List of benefits, below. |
| `earning_rates` | no | `[]` | `{category, multiplier, notes?}`; informational for now. |
| `au_terms` | no | | `{fee, own_lounge_access, notes?}` for authorized users. |

## Benefit

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `id` | yes | | Slug, unique within the product. Stable: renaming one closes every holder's open period for it. |
| `name` | yes | | Shown on every entity. The cadence is appended automatically when it is not yearly ("Uber Cash (monthly)"), so do not put it in the name. |
| `type` | yes | | See types below. |
| `cadence` | yes | | `monthly`, `quarterly`, `semiannual`, `annual`, `per_anniversary`, `one_time`. |
| `amount` | yes | | Dollars per period for a statement credit; points for an earning; `null` for perk, insurance and rebate. |
| `unit` | no | `USD` | `USD`, or `points` / `miles` for earnings. |
| `reset` | no | `calendar` | `calendar` (January, quarters, halves) or `cardmember_year` (anchored on the account anniversary). `per_anniversary` implies `cardmember_year`. |
| `enrollment_required` | no | `false` | The holder must enroll or activate before it pays. |
| `applies_to` | no | `primary` | `primary`, `primary_and_au` (authorized users share the primary's allotment), `au_own_allotment` (each authorized user gets their own). |
| `default_value` | no | | For perks and insurance: what a year of it is worth if the holder does not set a value. |
| `expires_days_after_open` | no | | One-time benefits only: deadline counted from the open date. |
| `spend_required` | no | | Sign-up bonus spend requirement, dollars. |
| `notes` | no | | Fine print. Shown in the card form. |
| `statement_match` | no | `[]` | Regular expressions, case-insensitive, matched against the description of credit lines. See below. |
| `conditional` | no | `false` | Only some holders qualify; off until enabled on the card. |
| `condition` | no | | Plain-language qualification, shown next to the toggle in the card form. |
| `shared_key` | no | | Perks and insurance only. The same thing on several cards (Priority Pass, Centurion Lounge, cell phone protection) is one membership, so give each copy the same key: the household values it once and the value is split equally between the active cards that carry it. Keys are catalog-wide, so `priority_pass` on an Amex and a Chase card share. |

### Types

- `statement_credit`: a capped amount per period that the issuer refunds. The only type
  with a dollar `amount`. What CardPerks mostly tracks.
- `perk`: something with no issuer amount, valued by the holder: lounge access, hotel
  status, free bags. Gets a value number entity.
- `insurance`: like a perk, kept separate so it can be shown apart.
- `rebate`: a share of spend returned with no cap (25% back on inflight purchases).
  `amount` must be `null`. Nothing to check off and nothing to forfeit; a year of it is
  worth whatever the statements showed.
- `earning`: points or miles, no dollars. Used for the sign-up bonus (`id` must be
  `sub`) and anniversary bonuses.

### Cadence and reset, in practice

| Benefit | `cadence` | `reset` |
| --- | --- | --- |
| $25 a month, January to December | `monthly` | `calendar` |
| $100 a quarter | `quarterly` | `calendar` |
| $150 January to June and again July to December | `semiannual` | `calendar` |
| $200 per calendar year | `annual` | `calendar` |
| $300 each account anniversary year | `annual` | `cardmember_year` |
| 10,000 miles on each anniversary | `per_anniversary` | (implied) |
| Sign-up bonus | `one_time` | with `spend_required` and `expires_days_after_open` |

A credit worth more in one month than the others (Uber Cash's December bonus) is entered
at the regular amount with the extra in `notes`; the model has one amount per period.

### Statement matching

When a statement is imported, every credit line's description is tested against each
benefit's `statement_match` patterns in catalog order, first hit wins. Patterns are
Python regular expressions, case-insensitive, searched anywhere in the description:

```json
"statement_match": ["TRAVEL CREDIT", "DOORDASH.*CREDIT"]
```

Keep them specific enough not to catch a different benefit on the same card ("HOTEL
CREDIT" would also match "UNITED HOTEL CREDIT" on a card that has both). Only credit
lines are tested, so a pattern never matches a purchase.

The line wording comes from real statements. Until one has been seen, either leave
`statement_match` empty (the credit is ticked off by hand) or mark the guess in `notes`.
A holder who sees the real line can add it without editing files with the
`cardperks.add_statement_match` action, which writes the product into their override
folder.

## Overrides

Files in `config/cardperks/catalog/` are loaded after the shipped ones, in name order. A
product with the same `id` as a shipped one replaces it completely, so an override file
carries the whole product. That is deliberate: the file reads on its own and the loader
has no merge rules to explain. A file that fails validation is skipped and reported in
Repairs; the shipped product stays in force.

The `cardperks.add_statement_match` action writes `<issuer>.json` into that folder. If
you later want the shipped entry back, delete the product from the override file.

## Contributing a product

1. Copy the closest existing product in the issuer's file, or start a new issuer file
   with the layout above.
2. Fill it from the issuer's page. Set `last_verified` to today and `needs_verification`
   to `false` only if you checked every benefit.
3. Run the validator; it is the same loader the integration uses:

   ```bash
   .venv-win/Scripts/python.exe -c "from custom_components.cardperks.catalog import load_catalog, SHIPPED_DIR; c, p = load_catalog(SHIPPED_DIR); print(p or 'ok')"
   ```

4. Run the tests and open a pull request that says what you checked and where.

Adding a statement parser for a new issuer is a code change in `statements.py`: a
`detect_issuer` rule for the export's header and a branch that maps its columns to date,
description, amount and card number.
