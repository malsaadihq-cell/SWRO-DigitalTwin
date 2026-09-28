"""Plant schematic drawn as inline SVG.

One picture of the whole skid — pump, membrane, brine valve — shown on
every page. The block that the current mode simulates is drawn in the
accent colour; the others fade back, so the page always says "this is
the part you are looking at, inside the whole plant".

Colours use `currentColor` for everything inactive, so the drawing
follows the app's light/dark theme automatically. Only the active block
is painted in the fixed accent teal.
"""
from __future__ import annotations

ACCENT = "#0F766E"


def _pen(block: str, active: str) -> tuple[str, str, str]:
    """Return (stroke colour, opacity, stroke width) for a block."""
    on = active in ("all", block)
    if on:
        return ACCENT, "1", "3"
    return "currentColor", "0.25", "2"


def system_svg(active: str = "all") -> str:
    """Full-skid schematic. `active` in {all, pump, membrane, valve}."""
    ps, po, pw = _pen("pump", active)
    ms, mo, mw = _pen("membrane", active)
    vs, vo, vw = _pen("valve", active)

    return f'''
<svg viewBox="0 0 860 250" width="100%" style="height:auto"
     xmlns="http://www.w3.org/2000/svg"
     font-family="var(--font, sans-serif)">

  <!-- pipes (always neutral, context only) -->
  <g stroke="currentColor" stroke-width="2.5" opacity="0.4" fill="none">
    <line x1="20"  y1="110" x2="102" y2="110"/>   <!-- feed -->
    <line x1="178" y1="110" x2="330" y2="110"/>   <!-- pump -> membrane -->
    <line x1="540" y1="110" x2="690" y2="110"/>   <!-- membrane -> node -->
    <line x1="690" y1="110" x2="800" y2="110"/>   <!-- node -> product -->
    <line x1="690" y1="110" x2="690" y2="176"/>   <!-- node -> valve -->
    <line x1="690" y1="204" x2="690" y2="224"/>   <!-- valve -> brine -->
  </g>

  <!-- PUMP -->
  <g stroke="{ps}" opacity="{po}" stroke-width="{pw}" fill="none">
    <circle cx="140" cy="110" r="38"/>
    <polygon points="120,86 120,134 176,110"/>
  </g>
  <text x="140" y="52"  fill="{ps}" opacity="{po}" font-size="15"
        text-anchor="middle" font-weight="600">VFD</text>
  <text x="140" y="172" fill="{ps}" opacity="{po}" font-size="13"
        text-anchor="middle">Pump (PD)</text>
  <text x="140" y="188" fill="{ps}" opacity="{po}" font-size="11"
        text-anchor="middle">APP 11/1500</text>

  <!-- MEMBRANE -->
  <g stroke="{ms}" opacity="{mo}" stroke-width="{mw}" fill="none">
    <rect x="330" y="78" width="210" height="64" rx="3"/>
  </g>
  <text x="435" y="60"  fill="{ms}" opacity="{mo}" font-size="15"
        text-anchor="middle" font-weight="600">&#916;P</text>
  <text x="435" y="164" fill="{ms}" opacity="{mo}" font-size="13"
        text-anchor="middle">Membrane</text>
  <text x="435" y="180" fill="{ms}" opacity="{mo}" font-size="11"
        text-anchor="middle">SWC4 MAX</text>

  <!-- VALVE (brine throttle, bowtie symbol) -->
  <g stroke="{vs}" opacity="{vo}" stroke-width="{vw}" fill="none">
    <polygon points="675,178 705,178 690,192"/>
    <polygon points="675,206 705,206 690,192"/>
  </g>
  <text x="716" y="190" fill="{vs}" opacity="{vo}" font-size="12"
        text-anchor="start">Globe valve</text>
  <text x="690" y="242" fill="{vs}" opacity="{vo}" font-size="12"
        text-anchor="middle">brine</text>

  <!-- product label -->
  <text x="806" y="114" fill="currentColor" opacity="0.7" font-size="13"
        text-anchor="start">product</text>
</svg>'''.strip()


# mode name (as shown in the UI) -> which block is highlighted
MODE_TO_BLOCK = {
    "Full system": "all",
    "Pump only": "pump",
    "Membrane only": "membrane",
    "Valve only": "valve",
}
