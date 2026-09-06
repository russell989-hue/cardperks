#!/usr/bin/env python3
"""Replace one view in a storage-mode dashboard, live, from the HA SSH add-on.

Uses the same websocket command the UI editor uses (lovelace/config/save), so the
change applies immediately with no restart and no direct .storage editing.

Usage (on the HA box):
  python3 push_dashboard.py <url_path> <view_path> <view.json>

<view.json> may hold a single view object, or a list of views. A list is merged by
each view's own path and <view_path> is ignored, so existing views are left alone.
e.g.
  python3 push_dashboard.py scratchpad-dashboard-wips cardperks /tmp/view.json

Layout set in the UI (section spans, cards stretched to full width) is carried over
from the view being replaced unless the new view sets its own.

Auth: SUPERVISOR_TOKEN from the add-on environment.
Backs the current config up to $CARDPERKS_BACKUP_DIR (default /tmp) first.
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client

LAYOUT_KEYS = ("column_span", "row_span")
CARD_LAYOUT_KEYS = ("grid_options", "layout_options")


def keep_layout(new: dict, old: dict) -> dict:
    """Carry layout set in the UI from the old section (or view) into its replacement.

    Section-level spans, and per-card grid options where the card at the same index
    is the same type, survive a regeneration unless the generator sets its own.
    """
    for key in LAYOUT_KEYS:
        if key in old and key not in new:
            new[key] = old[key]
    for new_card, old_card in zip(new.get("cards", []), old.get("cards", []), strict=False):
        if new_card.get("type") != old_card.get("type"):
            continue
        for key in CARD_LAYOUT_KEYS:
            if key in old_card and key not in new_card:
                new_card[key] = old_card[key]
    for new_sec, old_sec in zip(new.get("sections", []), old.get("sections", []), strict=False):
        keep_layout(new_sec, old_sec)
    return new


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
        payload = json.load(fh)
    # One view, or a list of views merged by their own path.
    views_in = payload if isinstance(payload, list) else [payload]

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
    for view in views_in:
        path = view.get("path") if isinstance(payload, list) else view_path
        view["path"] = path
        for i, v in enumerate(views):
            if v.get("path") == path:
                views[i] = keep_layout(view, v)
                print(f"replaced view '{path}'")
                break
        else:
            views.append(view)
            print(f"appended view '{path}'")

    cmd(type="lovelace/config/save", url_path=url_path, config=config)
    print(f"saved {url_path}: {len(views)} views total")
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
