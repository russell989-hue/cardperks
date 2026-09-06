#!/usr/bin/env python3
"""Dump the live CardPerks card map from a Home Assistant box, as JSON on stdout.

Keyed by card id: title, colour, the card-level entity ids, the status select, and
the perk-value number entities. Run inside the SSH add-on (uses SUPERVISOR_TOKEN).
"""

import json
import os
import urllib.request

tok = os.environ["SUPERVISOR_TOKEN"]
req = urllib.request.Request(
    "http://supervisor/core/api/states", headers={"Authorization": f"Bearer {tok}"}
)
states = json.loads(urllib.request.urlopen(req, timeout=30).read())

SUFFIXES = (
    (" Annual fee due", "fee_due"),
    (" Unused value", "unused_value"),
    (" Net value (12 months)", "net_value"),
    (" Fee due within 45 days", "fee_soon"),
    (" Annual credit value", "annual_value"),
    (" Captured, 12 months", "captured"),
    (" Forfeited, 12 months", "forfeited"),
    (" Capture rate", "capture_rate"),
    (" Statement coverage", "coverage"),
)

cards: dict[str, dict] = {}
for s in states:
    a = s.get("attributes", {})
    eid = s["entity_id"]
    if "card_id" not in a:
        continue
    c = cards.setdefault(
        a["card_id"],
        {
            "title": None,
            "color": None,
            "status": None,
            "perks": [],
            "card": {},
            "status_entity": None,
        },
    )
    c["title"] = c["title"] or a.get("card")
    c["color"] = c["color"] or a.get("color")
    c["status"] = c["status"] or a.get("card_status")
    fn = a.get("friendly_name", "")
    if eid.startswith("select.") and fn.endswith(" Status"):
        c["status_entity"] = eid
    if eid.startswith("number.") and "catalog_default" in a:
        c["perks"].append({"entity": eid, "benefit": a.get("benefit")})
    for suffix, key in SUFFIXES:
        if fn.endswith(suffix):
            c["card"][key] = eid

for c in cards.values():
    c["perks"].sort(key=lambda p: p["benefit"] or "")
print(json.dumps(cards, indent=1, sort_keys=True))
