#!/usr/bin/env python3
"""Render every template in the generated dashboard files in strict mode.

Run inside the SSH add-on after uploading the generated files to /tmp/dash. The
markdown card renders strictly, so an attribute a sensor lacks is an error there;
this catches it before a push. Also prints the By card bars, a subview ring and its
gauges as a smoke test.

  python3 verify_templates.py
"""

import ast
import json
import os

import websocket


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


tok = os.environ["SUPERVISOR_TOKEN"]
ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=60)
ws.recv()
ws.send(json.dumps({"type": "auth", "access_token": tok}))
ws.recv()
mid = 0


def strict(t):
    global mid
    mid += 1
    ws.send(
        json.dumps(
            {
                "id": mid,
                "type": "render_template",
                "template": t,
                "strict": True,
                "report_errors": True,
                "timeout": 10,
            }
        )
    )
    while True:
        m = json.loads(ws.recv())
        if m.get("id") != mid:
            continue
        if m.get("type") == "result" and not m.get("success"):
            return "ERROR " + json.dumps(m.get("error"))[:200]
        if m.get("type") == "event":
            ev = m["event"]
            return ("ERROR " + str(ev["error"])[:200]) if "error" in ev else ev.get("result")


def templates(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from templates(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from templates(v, f"{path}[{i}]")
    elif isinstance(obj, str) and ("{{" in obj or "{%" in obj):
        yield path, obj


PRE = "{% set entity = 'sensor.sapphire_reserve_brian_1234_annual_fee_due' %}{% set config = {'entity': entity} %}"
bad = total = 0
sources = [
    (n, load(f"/tmp/dash/sections/{n}.json"))
    for n in (
        "outstanding",
        "net_value",
        "checkoff",
        "perk_values",
        "dollars_left",
        "fees",
        "by_card",
        "expiring",
        "coverage",
    )
]
sources += [(v["path"], v) for v in load("/tmp/dash/views.json")]
for name, obj in sources:
    for path, t in templates(obj):
        total += 1
        r = strict(PRE + t)
        if isinstance(r, str) and r.startswith("ERROR"):
            bad += 1
            print(name, path, r)
print(f"strict errors: {bad} of {total} templates")
bars = strict(load("/tmp/dash/sections/by_card.json")["cards"][2]["filter"]["template"])
bars = bars if isinstance(bars, list) else ast.literal_eval(bars)
print(
    len(bars),
    "bars; first:",
    " ".join(bars[0]["content"].split())[:90],
    "|",
    bars[0]["card_mod"]["style"][:70],
)
v = load("/tmp/dash/views.json")[0]
ring = v["sections"][0]["cards"][1]
print("ring:", " ".join(str(strict(ring["content"])).split()))
g = v["sections"][1]["cards"]
for i in (3, 4, 5):
    r = strict(g[i]["filter"]["template"])
    r = r if isinstance(r, list) else ast.literal_eval(r)
    print("gauge:", r[0]["name"], r[0]["min"], r[0]["max"], r[0]["entity"])
