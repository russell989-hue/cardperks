"""Portability guard: the core must not depend on Home Assistant.

The modules below are the part of CardPerks that would carry over to any other host,
a standalone app included: period math, the rollover, statement parsing and matching,
the models, and the catalog loader and page. They stay importable with no Home
Assistant on the path. This test is deliberately simple and strict, like the privacy
guard: if it fails, a core module has grown a Home Assistant import and the core is
no longer portable.
"""

from __future__ import annotations

import re
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "cardperks"
CORE_MODULES = (
    "periods.py",
    "rollover.py",
    "statements.py",
    "models.py",
    "catalog.py",
    "catalog_page.py",
    "catalog_write.py",
    "const.py",
)
HA_IMPORT = re.compile(r"^\s*(import|from)\s+homeassistant\b", re.MULTILINE)


def test_core_modules_do_not_import_home_assistant() -> None:
    offenders = [
        name for name in CORE_MODULES if HA_IMPORT.search((COMPONENT_DIR / name).read_text("utf-8"))
    ]
    assert not offenders, f"Home Assistant imported in core modules: {offenders}"


def test_core_modules_only_import_each_other() -> None:
    """A core module may import the standard library, voluptuous, and other core modules."""
    core_names = {n.removesuffix(".py") for n in CORE_MODULES}
    relative = re.compile(r"^\s*from\s+\.(\w+)\s+import", re.MULTILINE)
    offenders = []
    for name in CORE_MODULES:
        for target in relative.findall((COMPONENT_DIR / name).read_text("utf-8")):
            if target not in core_names:
                offenders.append(f"{name} -> .{target}")
    assert not offenders, f"Core modules reaching outside the core: {offenders}"
