#!/usr/bin/env python3
"""Append one section to an existing dashboard view, live, from the HA SSH add-on.

Pulls the current config first and only adds, so hand-edited views are preserved.
Idempotent: a section whose first card has the same heading is replaced, not duplicated.

Usage (on the HA box):
  python3 append_section.py <url_path> <view_path> <section.json>
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client


def heading_of(section: dict) -> str | None:
    for card in section.get("cards", []):
        if card.get("type") == "heading":
            return card.get("heading")
    return None


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    url_path, view_path, section_file = sys.argv[1], sys.argv[2], sys.argv[3]
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        print("SUPERVISOR_TOKEN not set; run this inside the SSH add-on")
        return 2

    with open(section_file, encoding="utf-8") as fh:
        section = json.load(fh)

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

    view = next((v for v in config.get("views", []) if v.get("path") == view_path), None)
    if view is None:
        print(f"no view with path '{view_path}'")
        return 1
    if view.get("type") != "sections":
        print(f"view '{view_path}' is not a sections view")
        return 1

    sections = view.setdefault("sections", [])
    want = heading_of(section)
    for i, s in enumerate(sections):
        if want is not None and heading_of(s) == want:
            sections[i] = section
            print(f"replaced existing '{want}' section at index {i}")
            break
    else:
        sections.append(section)
        print(f"appended '{want}' section; view now has {len(sections)} sections")

    cmd(type="lovelace/config/save", url_path=url_path, config=config)
    print(f"saved {url_path}")
    ws.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
