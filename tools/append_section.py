#!/usr/bin/env python3
"""Append one section to an existing dashboard view, live, from the HA SSH add-on.

Pulls the current config first and only adds, so hand-edited views are preserved.
Idempotent: a section whose first card has the same heading is replaced, not duplicated.

Layout set in the UI (a two-column span, a card stretched to full width) is carried
over from the section being replaced unless the new section sets its own.

Usage (on the HA box):
  python3 append_section.py <url_path> <view_path> <section.json> [--was "<old heading>"]

--was replaces the section that currently has the old heading, in place, when a
section has been renamed.
"""

from __future__ import annotations

import json
import os
import sys
import time

import websocket  # websocket-client


def heading_of(section: dict) -> str | None:
    """The section's first heading, looking inside wrapper cards such as an expander."""

    def walk(card: dict) -> str | None:
        if card.get("type") == "heading":
            return card.get("heading")
        for inner in ([card["title-card"]] if isinstance(card.get("title-card"), dict) else []) + [
            c for c in card.get("cards", []) if isinstance(c, dict)
        ]:
            if (found := walk(inner)) is not None:
                return found
        return None

    for card in section.get("cards", []):
        if (found := walk(card)) is not None:
            return found
    return None


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
    args = list(sys.argv[1:])
    was = None
    if "--was" in args:
        i = args.index("--was")
        was = args[i + 1]
        del args[i : i + 2]
    if len(args) != 3:
        print(__doc__)
        return 2
    url_path, view_path, section_file = args
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
        if (want is not None and heading_of(s) == want) or (was and heading_of(s) == was):
            sections[i] = keep_layout(section, s)
            print(f"replaced existing '{heading_of(s)}' section at index {i}")
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
