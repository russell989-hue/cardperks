#!/usr/bin/env python3
"""Replace one view in a storage-mode dashboard, live, from the HA SSH add-on.

Uses the same websocket command the UI editor uses (lovelace/config/save), so the
change applies immediately with no restart and no direct .storage editing.

Usage (on the HA box):
  python3 push_dashboard.py <url_path> <view_path> <view.json>
e.g.
  python3 push_dashboard.py scratchpad-dashboard-wips cardperks /tmp/view.json

Auth: SUPERVISOR_TOKEN from the add-on environment.
Backs the current config up to $CARDPERKS_BACKUP_DIR (default /tmp) first.
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    url_path, view_path, view_file = sys.argv[1], sys.argv[2], sys.argv[3]
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not set; run this inside the SSH add-on")
        return 2

    with open(view_file, encoding="utf-8") as fh:
        view = json.load(fh)

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

    views = config.setdefault("views", [])
    for i, v in enumerate(views):
        if v.get("path") == view_path:
            views[i] = view
            print(f"replaced view '{view_path}' at index {i}")
            break
    else:
        views.append(view)
        print(f"appended new view '{view_path}'")

    cmd(type="lovelace/config/save", url_path=url_path, config=config)
    print(
        f"saved {url_path}: {len(views)} views, "
        f"{len(view.get('sections', []))} sections in '{view_path}'"
    )
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
