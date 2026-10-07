"""Bundled font pairings (all SIL Open Font License; see each family's OFL.txt).

Fonts are inlined into the rendered HTML as data: URIs, so Chromium never makes a request while
rendering. Only Latin and Latin Extended subsets are bundled; other scripts fall back to system fonts.
The files are static weights, not variable fonts: Chromium can only embed variable fonts in a PDF as Type3
glyph outlines, which some résumé parsers read badly, while static fonts embed as ordinary TrueType.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import cache
from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"

# unicode-range values from the font packages (fontsource), so each file is used only where it applies
_LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,"
          "U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
_LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,"
              "U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")


@dataclass(frozen=True)
class Family:
    name: str  # CSS family name
    folder: str
    fallback: str
    weights: tuple[int, ...] = (400, 500, 600, 700)
    italic_weights: tuple[int, ...] = (400,)


@dataclass(frozen=True)
class Pairing:
    key: str
    label: str
    heading: Family
    body: Family


# Fallbacks cover characters outside the bundled subsets (arrows, other scripts). The Liberation fonts ship in
# the container image and embed normally.
SANS = "'Liberation Sans', Arial, sans-serif"
SERIF = "'Liberation Serif', Georgia, serif"
INTER = Family("Inter", "inter", SANS)
PLEX = Family("IBM Plex Sans", "ibm-plex-sans", SANS)
SOURCE_SANS = Family("Source Sans 3", "source-sans-3", SANS)
SOURCE_SERIF = Family("Source Serif 4", "source-serif-4", SERIF)
GARAMOND = Family("EB Garamond", "eb-garamond", SERIF)
LATO = Family("Lato", "lato", SANS, weights=(400, 700), italic_weights=(400, 700))
MERRIWEATHER = Family("Merriweather", "merriweather", SERIF)

PAIRINGS: dict[str, Pairing] = {
    "inter": Pairing("inter", "Inter", INTER, INTER),
    "plex": Pairing("plex", "IBM Plex Sans", PLEX, PLEX),
    "source": Pairing("source", "Source Sans 3 / Source Serif 4", SOURCE_SANS, SOURCE_SERIF),
    "garamond": Pairing("garamond", "EB Garamond / Source Serif 4", GARAMOND, SOURCE_SERIF),
    "lato": Pairing("lato", "Lato / Merriweather", LATO, MERRIWEATHER),
}


def _data_uri(path: Path) -> str:
    return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _faces(family: Family) -> list[str]:
    rules = []
    faces = [(w, "normal") for w in family.weights] + [(w, "italic") for w in family.italic_weights]
    for subset, unicode_range in (("latin", _LATIN), ("latin-ext", _LATIN_EXT)):
        for weight, style in faces:
            file = FONT_DIR / family.folder / f"{family.folder}-{subset}-{weight}-{style}.woff2"
            rules.append(
                f"@font-face{{font-family:'{family.name}';font-style:{style};font-weight:{weight};"
                f"font-display:block;src:url({_data_uri(file)}) format('woff2');unicode-range:{unicode_range};}}"
            )
    return rules


@cache
def font_css(key: str) -> str:
    """@font-face rules for a pairing, cached (a few hundred KB of base64 per pairing)."""
    pairing = PAIRINGS[key]
    families = {pairing.heading.name: pairing.heading, pairing.body.name: pairing.body}
    return "\n".join(rule for family in families.values() for rule in _faces(family))


def stack(family: Family) -> str:
    return f"'{family.name}', {family.fallback}"
