"""Privacy guard: no module in the integration may import a network client.

This test is intentionally simple and strict. If it fails, a module other than
the sanctioned one has gained the ability to make network calls, which
violates the project's core guarantee that no user data leaves the machine.
"""

from __future__ import annotations

import re
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "cardperks"
ALLOWED_NETWORK_MODULES: set[str] = set()  # cardperks makes no network calls at all
NETWORK_IMPORT = re.compile(
    r"^\s*(import|from)\s+(aiohttp|requests|httpx|urllib|socket|http\.client)\b",
    re.MULTILINE,
)


def test_no_module_touches_the_network() -> None:
    offenders = []
    for path in COMPONENT_DIR.rglob("*.py"):
        if path.name in ALLOWED_NETWORK_MODULES:
            continue
        if NETWORK_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(COMPONENT_DIR)))
    assert not offenders, f"Unexpected network imports in: {offenders}"
