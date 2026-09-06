#!/usr/bin/env python3
"""Put a dashboard's views in a given order, live, from the SSH add-on.

Views named come first in that order; every other view keeps its relative order after
them. Nothing inside any view changes.

  python3 reorder_views.py <url_path> <path> [<path> ...]
  python3 reorder_views.py dashboard-cardperks cardperks money upkeep
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    url_path, order = sys.argv[1], sys.argv[2:]
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not set; run this inside the SSH add-on")
        return 2

    ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=30)
    assert json.loads(ws.recv())["type"] == "auth_required"
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if json.loads(ws.recv())["type"] != "auth_ok":
        print("auth failed")
        return 1
    mid = 0

    def cmd(**payload):
        nonlocal mid
        mid += 1
        ws.send(json.dumps({"id": mid, **payload}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid and msg.get("type") == "result":
                if not msg.get("success"):
                    raise SystemExit(f"command failed: {msg.get('error')}")
                return msg.get("result")

    config = cmd(type="lovelace/config", url_path=url_path)
    backup_dir = os.environ.get("CARDPERKS_BACKUP_DIR", "/tmp")
    backup = f"{backup_dir}/cardperks_dashboard_backup_{int(time.time())}.json"
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    print(f"backed up current config to {backup}")

    views = config.get("views", [])
    by_path = {v.get("path"): v for v in views}
    missing = [p for p in order if p not in by_path]
    if missing:
        print(f"no view with path: {missing}")
        return 1
    first = [by_path[p] for p in order]
    rest = [v for v in views if v.get("path") not in order]
    config["views"] = first + rest
    cmd(type="lovelace/config/save", url_path=url_path, config=config)
    print("order:", [v.get("path") for v in config["views"]])
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
