"""Pack registry — the catalog of available verticals. Add a vertical here."""
from __future__ import annotations

from .base import CopilotPack, PackManifest
from .sales import SalesPack

_sales = SalesPack()

PACKS: dict[str, CopilotPack] = {
    _sales.manifest.key: _sales,
    # "developer": DeveloperPack(),   # see docs/PLATFORM_EXTENSIBILITY.md
    # "product":   ProductPack(),
}

DEFAULT_PACK = "sales"


def get_pack(key: str | None) -> CopilotPack:
    return PACKS.get(key or DEFAULT_PACK, _sales)


def list_packs() -> list[PackManifest]:
    return [p.manifest for p in PACKS.values()]
