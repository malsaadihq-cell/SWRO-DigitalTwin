"""Plant schematic drawn as inline SVG.

One picture of the whole skid — pump, membrane, brine valve — shown on
every page. The block the current mode simulates is drawn in the accent
colour; the others fade back, so the page always says "this is the part
you are looking at, inside the whole plant".

Everything inactive uses `currentColor`, so the drawing follows the app's
light/dark theme automatically. Only the active block is painted teal.
No comments are placed inside the <svg> markup on purpose: some HTML
sanitizers reparent the node that follows a comment.
"""
from __future__ import annotations

ACCENT = "#0F766E"


def _pen(block: str, active: str) -> tuple[str, str, str]:
    """Return (stroke colour, opacity, stroke width) for a block."""
    if active in ("all", block):
        return ACCENT, "1", "3"
    return "currentColor", "0.25", "2"


def system_svg(active: str = "all") -> str:
    """Full-skid schematic. `active` in {all, pump, membrane, valve}."""
    ps, po, pw = _pen("pump", active)
    ms, mo, mw = _pen("membrane", active)
    vs, vo, vw = _pen("valve", active)

    return f'''<svg viewBox="0 0 840 230" width="100%" style="height:auto"
     xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
  <g stroke="currentColor" stroke-width="2.5" opacity="0.4" fill="none">
    <line x1="20"  y1="105" x2="104" y2="105"/>
    <line x1="176" y1="105" x2="330" y2="105"/>
    <line x1="540" y1="105" x2="680" y2="105"/>
    <line x1="680" y1="105" x2="800" y2="105"/>
    <line x1="680" y1="105" x2="680" y2="166"/>
    <line x1="680" y1="190" x2="680" y2="206"/>
  </g>
  <g stroke="{ps}" opacity="{po}" stroke-width="{pw}" fill="none">
    <circle cx="140" cy="105" r="36"/>
    <polygon points="122,83 122,127 174,105"/>
  </g>
  <text x="140" y="50"  fill="{ps}" opacity="{po}" font-size="15" text-anchor="middle" font-weight="600">VFD</text>
  <text x="140" y="162" fill="{ps}" opacity="{po}" font-size="13" text-anchor="middle">Pump (PD)</text>
  <text x="140" y="178" fill="{ps}" opacity="{po}" font-size="11" text-anchor="middle">APP 11/1500</text>
  <g stroke="{ms}" opacity="{mo}" stroke-width="{mw}" fill="none">
    <rect x="330" y="75" width="210" height="60" rx="3"/>
  </g>
  <text x="435" y="58"  fill="{ms}" opacity="{mo}" font-size="15" text-anchor="middle" font-weight="600">&#916;P</text>
  <text x="435" y="158" fill="{ms}" opacity="{mo}" font-size="13" text-anchor="middle">Membrane</text>
  <text x="435" y="174" fill="{ms}" opacity="{mo}" font-size="11" text-anchor="middle">SWC4 MAX</text>
  <g stroke="{vs}" opacity="{vo}" stroke-width="{vw}" fill="none">
    <polygon points="665,166 695,166 680,178"/>
    <polygon points="665,190 695,190 680,178"/>
  </g>
  <text x="704" y="182" fill="{vs}" opacity="{vo}" font-size="12" text-anchor="start">Globe valve</text>
  <text x="680" y="224" fill="{vs}" opacity="{vo}" font-size="12" text-anchor="middle">brine</text>
  <text x="748" y="94"  fill="currentColor" opacity="0.7" font-size="13" text-anchor="middle">product</text>
</svg>'''


MODE_TO_BLOCK = {
    "Full system": "all",
    "Pump only": "pump",
    "Membrane only": "membrane",
    "Valve only": "valve",
}
