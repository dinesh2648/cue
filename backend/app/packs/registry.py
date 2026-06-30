"""Pack registry — the catalog of available verticals. Add a vertical here."""
from __future__ import annotations

from .base import CopilotPack, PackManifest
from .sales import SalesPack
from .tech import TechPack

_sales = SalesPack()
_tech = TechPack()

PACKS: dict[str, CopilotPack] = {
    _sales.manifest.key: _sales,
    _tech.manifest.key: _tech,
    # "product":   ProductPack(),     # see docs/PLATFORM_EXTENSIBILITY.md
}

DEFAULT_PACK = "sales"

# Employee team → which Copilot Pack drives their meetings.
_TEAM_PACK = {"sales": "sales", "tech": "tech", "ops": "sales"}


def pack_for_team(team: str | None) -> str:
    return _TEAM_PACK.get((team or "sales").lower(), "sales")


def get_pack(key: str | None) -> CopilotPack:
    return PACKS.get(key or DEFAULT_PACK, _sales)


def list_packs() -> list[PackManifest]:
    return [p.manifest for p in PACKS.values()]
