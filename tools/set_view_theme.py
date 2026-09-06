#!/usr/bin/env python3
"""Set the theme on one view of a storage-mode dashboard, live, from the SSH add-on.

Only the view's `theme` key changes; its sections, cards and hand-set layout are left
exactly as they are. Pass "" to remove the key.

  python3 set_view_theme.py <url_path> <view_path> "<theme name>"
  python3 set_view_theme.py dashboard-cardperks cardperks "CardPerks"
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
    url_path, view_path, theme = sys.argv[1:4]
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

    for view in config.get("views", []):
        if view.get("path") == view_path:
            before = view.get("theme")
            if theme:
                view["theme"] = theme
            else:
                view.pop("theme", None)
            cmd(type="lovelace/config/save", url_path=url_path, config=config)
            print(f"view '{view_path}': theme {before!r} -> {theme or None!r}")
            ws.close()
            return 0
    print(f"no view with path '{view_path}'")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
