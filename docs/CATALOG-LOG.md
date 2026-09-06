# Catalog change log

Dated record of what changed in the shipped catalog and why. Newest first. A future
standalone app can ship this as "what changed"; it is also the only honest history of
what was available when, since issuer pages do not publish theirs.

## 2026-09-06

- **Amex Business Platinum and Business Gold** read from the official pages in a browser and
  `needs_verification` cleared. Business Platinum gains the $300 ChatGPT Business credit,
  Leaders Club Sterling status and The Hotel Collection $100 credit; the welcome offer shown
  was 300,000 points after $20,000. Business Gold gains the $300 ChatGPT Business and $150
  Squarespace credits, the flexible credit is $240 a year (FedEx through 10/01/2026, Grubhub,
  office supply stores), and the welcome offer shown was 200,000 after $15,000.
- **Global Entry / TSA PreCheck** on every product: was a $120 statement credit per card per
  year; now a shared perk (`global_entry`) valued at $30 a year for the household. One fee
  every four years, claimable once, is what the issuers actually give.

Every shipped product checked against its issuer page; `needs_verification` cleared and
`last_verified` set. Verified from statements earlier: Chase fee months and amounts for
every Chase card, the Amex Platinum fee date and the Resy credit's quarterly cadence,
the Venture X fee month and amount, United inflight/club 25% rebate lines on the Club
card. United Club authorized users confirmed to get no club access of their own.

- **Amex Platinum**: CLEAR credit is $219; Uber Cash gets a $20 December bonus (noted,
  still $15 a month in the catalog); Delta Sky Club visits added as a perk.
- **Venture X**: additional cardholders no longer get Capital One Lounge access free ($125
  a year each); Hertz status is Gold Plus, not President's Circle; cell phone protection
  added.
- **Sapphire Reserve**: $250 select-hotels credit for 2026 only and IHG Platinum status
  added; notes on the split credits and their end dates.
- **Ink Business Preferred**: sign-up bonus is 100,000 points; $10 a month DoorDash credit
  added.
- **Southwest Plus**: fee is $99 (a card with a $69 statement line keeps its own override);
  EarlyBird credits replaced by standard seat selection under assigned seating; flight
  discount code, Companion Pass boost, 25% inflight rebate, DoorDash and Instacart
  credits, and free first bag added.
- **United Explorer and Club**: the 2025 refresh. Hotel, JSX and Avis/Budget credits are
  per anniversary year at the new amounts ($100/$100/$50 Explorer, $200/$200/$100 Club);
  Instacart is $10 and $20 a month; Club rideshare is $12 a month with $18 in December;
  Explorer gains the $100 TravelBank credit after $10,000 spend (conditional); Club gains
  award-flight discounts. Source URLs updated to the current Chase pages.
- **Added** from issuer pages: Amex Gold, Chase Sapphire Preferred, United Quest, Southwest
  Priority, Capital One Venture, Venture X Business. **Added from secondary sources**,
  flagged `needs_verification`: Amex Business Platinum, Amex Business Gold.
- **Shared perks** introduced (`shared_key`): Priority Pass, Centurion and Delta lounges,
  Amex hotel status, Capital One Lounge, cell phone protection, Hertz status, United and
  Southwest checked bags. Airline named in the checked-bag perk names.
- Still open: statement wording for the new credits is guessed until a statement shows the
  real line; Southwest sign-up bonus not restated on the page; Equinox credit on the
  Platinum not listed on the Amex page this pass and left in place.
