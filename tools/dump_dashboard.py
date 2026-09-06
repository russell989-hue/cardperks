#!/usr/bin/env python3
"""List a dashboard's views, sections and card types, from the SSH add-on.

python3 dump_dashboard.py <url_path>
"""

import json
import os
import sys

import websocket

ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=30)
ws.recv()
ws.send(json.dumps({"type": "auth", "access_token": os.environ["SUPERVISOR_TOKEN"]}))
ws.recv()
ws.send(json.dumps({"id": 1, "type": "lovelace/config", "url_path": sys.argv[1]}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        break
cfg = m["result"]
for v in cfg.get("views", []):
    print(
        f"view path={v.get('path')!r} title={v.get('title')!r} subview={v.get('subview', False)} type={v.get('type')}"
    )
    for i, s in enumerate(v.get("sections", [])):
        cards = s.get("cards", [])
        h = next((c.get("heading") for c in cards if c.get("type") == "heading"), None)
        types = [c.get("type") for c in cards]
        print(f"   [{i}] {h!r}: {types}")
