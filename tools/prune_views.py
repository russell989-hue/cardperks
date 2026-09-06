#!/usr/bin/env python3
"""Drop subviews whose path is no longer generated.

A card's subview path comes from its title, so renaming a card leaves the old view
behind as an orphan. This removes any subview not present in the given views file.
Non-subviews (a hand-built overview) are never touched.

Usage (on the HA box):
  python3 prune_views.py <url_path> <views.json>
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    url_path, views_file = sys.argv[1], sys.argv[2]
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not set; run this inside the SSH add-on")
        return 2

    with open(views_file, encoding="utf-8") as fh:
        keep = {v["path"] for v in json.load(fh)}

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
    dropped = [v["path"] for v in views if v.get("subview") and v.get("path") not in keep]
    if not dropped:
        print("no orphaned subviews")
        return 0
    config["views"] = [v for v in views if not (v.get("subview") and v.get("path") not in keep)]
    cmd(type="lovelace/config/save", url_path=url_path, config=config)
    print(f"removed {len(dropped)} orphaned subviews: {', '.join(dropped)}")
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
