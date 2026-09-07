# Generated dashboard views

`views_main.json` holds the three top-level views of the CardPerks dashboard
(Overview, Analysis, Upkeep) exactly as `tools/build_views.py` generates them. Every
list and ring is a template over entity attributes, so the file carries nothing about
any household: import it as it is and it fills in from your own cards.

It needs these HACS frontend cards: Mushroom, auto-entities, card-mod and
expander-card, plus the CardPerks theme from `themes/cardperks.yaml`.

To import: open the dashboard's raw configuration editor and paste the views under
`views:`, or run `tools/push_dashboard.py <dashboard-url-path> _ views_main.json`
from the SSH add-on. The per-card subviews are not shipped, because their titles
carry card names; generate them with `tools/cp_full.py` on the box and then
`tools/build_card_views.py`, as `HANDOFF.md` describes.
