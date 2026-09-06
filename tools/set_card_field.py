#!/usr/bin/env python3
"""Change one field on a card through its own reconfigure flow, from the SSH add-on.

Starts the held_card reconfigure flow over the REST API, carries every suggested value
over unchanged, and submits with one field changed, exactly as the form would. An empty
value clears the field (for example, to drop an annual fee override).

  python3 set_card_field.py <field> <value or ""> "<part of the card title>"
  python3 set_card_field.py annual_fee "" "Amex Platinum"
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


field_name, new_value, title_part = sys.argv[1], sys.argv[2], sys.argv[3]
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
values = {}
names = [f["name"] for f in form["data_schema"]]
assert field_name in names, f"no field {field_name}; form has {names}"
for f in form["data_schema"]:
    sv = (f.get("description") or {}).get("suggested_value")
    if sv is not None:
        values[f["name"]] = sv
before = values.get(field_name)
if new_value == "":
    values.pop(field_name, None)
else:
    values[field_name] = new_value
print(f"{card['attributes']['card']}: {field_name} {before!r} -> {new_value or None!r}")
res = call(f"/api/config/config_entries/subentries/flow/{form['flow_id']}", values)
print("result:", res.get("type"), res.get("reason"), res.get("errors"))
time.sleep(3)
