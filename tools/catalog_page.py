"""Render the shipped catalog to an HTML file, the same page the sidebar panel serves.

.venv-win/Scripts/python.exe tools/catalog_page.py out.html
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.cardperks.catalog import SHIPPED_DIR, load_catalog
from custom_components.cardperks.catalog_page import GOOGLE_FONTS, render_catalog

if __name__ == "__main__":
    catalog, problems = load_catalog(SHIPPED_DIR)
    assert not problems, problems
    out = Path(sys.argv[1])
    out.write_text(
        render_catalog(
            catalog, source_note="Rendered from the shipped JSON.", fonts_href=GOOGLE_FONTS
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")
