"""The integration ships its own brand icon (Home Assistant 2026.3+ serves it)."""

import struct
from pathlib import Path

BRAND = Path(__file__).parent.parent / "custom_components" / "cardperks" / "brand"


def _size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def test_brand_icons_are_the_sizes_home_assistant_expects():
    assert _size(BRAND / "icon.png") == (256, 256)
    assert _size(BRAND / "icon@2x.png") == (512, 512)
