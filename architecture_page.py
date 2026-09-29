"""Architecture overview page.

A compact, centered, designed rendering of the system architecture — styled
cards in the app's identity (warm paper, steel-blue accent), narrow and
centered so most of it fits on one screen without scrolling. Reachable from
the "Architecture" mode in the sidebar.
"""
from __future__ import annotations

import streamlit as st

ACC = "#285A7A"     # steel-blue accent
MUT = "#6B6459"     # muted description text
ARR = "#B7B0A2"     # arrows / connectors
BORD = "#DCD6C8"    # card border


def _box(title: str, desc: str, bg: str = "#F8F6F0") -> str:
    return (
        f'<div style="background:{bg};border:1px solid {BORD};'
        f'border-left:4px solid {ACC};border-radius:8px;padding:8px 12px">'
        f'<div style="font-weight:700;color:{ACC};font-size:13.5px">{title}</div>'
        f'<div style="color:{MUT};font-size:12px;line-height:1.35;'
        f'margin-top:2px">{desc}</div></div>'
    )


def _cell(title: str, desc: str) -> str:
    return (
        f'<div style="background:#FBFAF6;border:1px solid {BORD};'
        f'border-radius:6px;padding:6px 9px">'
        f'<div style="font-weight:700;color:{ACC};font-size:12.5px">{title}</div>'
        f'<div style="color:{MUT};font-size:11px;line-height:1.3;'
        f'margin-top:2px">{desc}</div></div>'
    )


def render() -> None:
    arrow = (f'<div style="text-align:center;color:{ARR};font-size:14px;'
             f'line-height:1;margin:4px 0">&#8595;</div>')

    plant = _box("Physical plant",
                 "The real SWRO skid — pump, membrane, brine valve, gauges. "
                 "What the twin mirrors and, later, advises.")

    flow_row = (
        f'<div style="display:flex;gap:10px;margin:4px 0">'
        f'<div style="flex:1;text-align:center;color:{ARR};font-size:11px">measures &#8595;</div>'
        f'<div style="flex:1;text-align:center;color:{ARR};font-size:11px">&#8593; advises</div>'
        f'</div>'
    )

    data = _box("Data layer",
                "Feeds the model: manufacturer specs, hand-read gauges, and each "
                "test-run's records. Feed salinity is from a grab sample, so it is "
                "lower-confidence.")
    advisory = _box("Advisory layer",
                    "Suggests back a recommended frequency &amp; valve opening. A "
                    "human reviews and executes — no automatic actuation.")
    da_row = (f'<div style="display:flex;gap:10px">'
              f'<div style="flex:1">{data}</div>'
              f'<div style="flex:1">{advisory}</div></div>')

    core = _cell("Model core", "Pump, membrane &amp; valve equations, from manufacturer data.")
    solver = _cell("Solver", "Couples the three blocks through one balancing pressure &#8594; operating point.")
    analysis = _cell("Analysis", "KPIs, performance curves &amp; the best operating window.")
    calib = _cell("Calibration", "Tunes A, B, Cv, efficiency to match this specific plant.")
    valid = _cell("Validation &amp; uncertainty", "Error band + threshold — a real change vs measurement noise.")
    assume = _cell("Assumptions &amp; limits", "Steady-state, single element, and the valid range.")
    diag = _cell("Diagnosis", "Model vs measured — a gap past the threshold flags wear or fouling.")

    model = (
        f'<div style="background:#ECE8DE;border:1px solid {BORD};border-radius:8px;'
        f'padding:10px 12px">'
        f'<div style="font-weight:700;color:{ACC};font-size:14px">Model — the digital twin</div>'
        f'<div style="color:{MUT};font-size:12px;margin-top:2px">The virtual copy of '
        f'the plant — it predicts, compares against measurements, and finds the best settings.</div>'
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px">'
        f'{core}{solver}{analysis}{calib}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">'
        f'{valid}{assume}</div>'
        f'<div style="margin-top:8px">{diag}</div>'
        f'</div>'
    )

    interface = _box("Interface",
                     "The web app — mode selector, controls, plant schematic, "
                     "KPIs, charts and sources.")
    people = _box("People",
                  "Operator runs &#183; examiner verifies &#183; developer builds.")

    platform = (
        f'<div style="background:#E3EAEF;border:1px solid #CBD8E0;border-radius:8px;'
        f'padding:8px 12px;text-align:center;color:{ACC};font-weight:600;'
        f'font-size:12.5px;margin-top:8px">Platform / delivery — code &amp; config '
        f'in one GitHub repo &#8594; Streamlit Cloud &#8594; web</div>'
    )

    loop = (
        f'<div style="text-align:center;color:{ARR};font-size:11px;margin-top:8px">'
        f'Loop: plant &#8594; data &#8594; model &#8594; interface &#8594; people '
        f'&#8594; advisory &#8594; (human) &#8594; plant</div>'
    )

    html = (
        f'<div style="max-width:760px;margin:0 auto;font-family:sans-serif">'
        f'<div style="font-size:23px;font-weight:800;color:#201E1A">System architecture</div>'
        f'<div style="color:{MUT};font-size:12.5px;margin:2px 0 12px">How the whole '
        f'digital twin fits together — plant, data, model, and people.</div>'
        f'{plant}{flow_row}{da_row}{arrow}{model}{arrow}{interface}{arrow}{people}'
        f'{platform}{loop}</div>'
    )

    st.markdown(html, unsafe_allow_html=True)
