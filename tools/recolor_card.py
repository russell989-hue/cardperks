#!/usr/bin/env python3
"""Change one card's colour through its own reconfigure flow, from the SSH add-on.

Starts the held_card reconfigure flow over the REST API, carries every suggested
value over unchanged, and submits with the colour swapped, exactly as the form would.

  python3 recolor_card.py <colour> "<part of the card title>"
"""

import json
import os
import sys
import time
import urllib.request

tok = os.environ["SUPERVISOR_TOKEN"]
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def call(url, body=None):
    req = urllib.request.Request(
        "http://supervisor/core" + url,
        data=json.dumps(body).encode() if body is not None else None,
        headers=H,
        method="POST" if body is not None else "GET",
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {url}: {e.read().decode()[:300]}") from None


wanted = sys.argv[1]
title_part = sys.argv[2]
states = call("/api/states")
card = next(
    s
    for s in states
    if s["attributes"].get("kind") == "capture_rate"
    and title_part in (s["attributes"].get("card") or "")
)
card_id = card["attributes"]["card_id"]
entry_id = next(
    e["entry_id"] for e in call("/api/config/config_entries/entry") if e["domain"] == "cardperks"
)
form = call(
    "/api/config/config_entries/subentries/flow",
    {"handler": [entry_id, "held_card"], "subentry_id": card_id},
)
assert form.get("type") == "form" and form.get("step_id") == "reconfigure", form
values, color_field = {}, None
for f in form["data_schema"]:
    sv = (f.get("description") or {}).get("suggested_value")
    if sv is not None:
        values[f["name"]] = sv
    opts = ((f.get("selector") or {}).get("select") or {}).get("options") or []
    if any((o if isinstance(o, str) else o.get("value")) == wanted for o in opts):
        color_field = f["name"]
assert color_field, "no colour field offering " + wanted
print("form fields carried over:", sorted(values))
values[color_field] = wanted
res = call(f"/api/config/config_entries/subentries/flow/{form['flow_id']}", values)
print("result:", res.get("type"), res.get("reason"), res.get("errors"))
for _ in range(20):
    time.sleep(2)
    st = call(f"/api/states/{card['entity_id']}")
    if st["attributes"].get("color") == wanted:
        print(card["attributes"]["card"], "is now", wanted)
        break
else:
    print("colour attribute not updated yet:", st["attributes"].get("color"))
