"""Theme options (DESIGN.md §11.4, TPL-3) and the per-template manifests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

ACCENTS = {
    "Navy": "#1F3A5F", "Teal": "#0F766E", "Emerald": "#047857", "Burgundy": "#7A1F3D",
    "Indigo": "#3730A3", "Copper": "#B4532A", "Slate": "#334155", "Graphite": "#111827",
}
MIN_CONTRAST = 4.5  # accent text on white, WCAG AA; also keeps it readable in grayscale print

FontKey = Literal["inter", "plex", "source", "garamond", "lato"]
Density = Literal["comfortable", "balanced", "compact"]
Paper = Literal["letter", "a4"]
Margins = Literal["normal", "narrow"]
DateFormat = Literal["MMM YYYY", "MM/YYYY", "YYYY"]


def contrast_with_white(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return 1.05 / (luminance + 0.05)


class Theme(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    accent: str = ACCENTS["Navy"]
    fonts: FontKey = "inter"
    density: Density = "balanced"
    paper: Paper = "letter"
    margins: Margins = "normal"
    date_format: DateFormat = "MMM YYYY"
    contact_icons: bool = True

    @field_validator("accent")
    @classmethod
    def _readable_accent(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("use a hex color like #1F3A5F")
        value = value.upper()
        if contrast_with_white(value) < MIN_CONTRAST:
            raise ValueError("this color is too light to read on white; choose a darker one")
        return value


@dataclass(frozen=True)
class DensitySpec:
    size_pt: float  # body text
    leading: float
    space: float  # multiplier for vertical spacing


DENSITIES: dict[str, DensitySpec] = {
    "comfortable": DensitySpec(10.2, 1.46, 1.15),
    "balanced": DensitySpec(9.5, 1.4, 1.0),  # 9.5 pt is the floor for body text (§11.2)
    "compact": DensitySpec(9.5, 1.32, 0.78),
}


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    label: str
    description: str
    layout: str
    ats: str
    available: bool
    # page margins (top, sides, bottom) in inches, per margin option
    margins: dict[str, tuple[float, float, float]]


TEMPLATES: dict[str, TemplateInfo] = {
    "meridian": TemplateInfo(
        "meridian", "Meridian", "Modern and crisp: a thin accent bar, a large name in the accent color, and "
        "small-caps section headings with a hairline rule.", "Single column", "Excellent", True,
        {"normal": (0.55, 0.65, 0.5), "narrow": (0.42, 0.5, 0.42)},
    ),
    "atlas": TemplateInfo("atlas", "Atlas", "Eye-catching two-column layout with a tinted sidebar.",
                          "Two columns", "Good", False, {"normal": (0.5, 0.5, 0.5), "narrow": (0.4, 0.4, 0.4)}),
    "ledger": TemplateInfo("ledger", "Ledger", "Classic and editorial, with a centered serif header.",
                           "Single column", "Excellent", False,
                           {"normal": (0.6, 0.75, 0.55), "narrow": (0.45, 0.5, 0.45)}),
    "vanguard": TemplateInfo("vanguard", "Vanguard", "Bold, with a full-width accent band and a label gutter.",
                             "Single column", "Very good", False,
                             {"normal": (0.5, 0.6, 0.5), "narrow": (0.4, 0.5, 0.4)}),
}
DEFAULT_TEMPLATE = "meridian"
