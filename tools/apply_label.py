#!/usr/bin/env python3
"""Apply a Home Assistant label to every CardPerks card device.

Labels are user-space, so the integration does not manage them. Run this after
adding cards to keep the label complete. Re-running is safe: a device that already
carries the label is left alone.

Usage (on the HA box):
  python3 apply_label.py "Credit Card" [--include-owners]
"""

from __future__ import annotations

import json
import os
import sys

import websocket  # websocket-client


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    label_name = sys.argv[1]
    include_owners = "--include-owners" in sys.argv
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

    labels = cmd(type="config/label_registry/list")
    label = next((label for label in labels if label["name"] == label_name), None)
    if label is None:
        print(f"no label named {label_name!r}. Create it in Settings > Areas & labels.")
        return 1

    entries = cmd(type="config_entries/get", domain="cardperks")
    entry_ids = {e["entry_id"] for e in entries}
    devices = cmd(type="config/device_registry/list")

    applied, already = [], []
    for device in devices:
        if not entry_ids.intersection(device.get("config_entries", [])):
            continue
        # Owner devices are service entries, not cards, unless asked for.
        identifiers = [i for i in device.get("identifiers", []) if i[0] == "cardperks"]
        is_owner = any(str(i[1]).startswith("owner:") for i in identifiers)
        if is_owner and not include_owners:
            continue
        name = device.get("name_by_user") or device.get("name")
        current = list(device.get("labels") or [])
        if label["label_id"] in current:
            already.append(name)
            continue
        cmd(
            type="config/device_registry/update",
            device_id=device["id"],
            labels=[*current, label["label_id"]],
        )
        applied.append(name)

    for name in applied:
        print(f"labelled {name}")
    if already:
        print(f"{len(already)} already had it")
    print(f"{len(applied)} newly labelled with {label_name!r}")
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
