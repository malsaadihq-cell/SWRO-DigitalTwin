"""Pump-only view.

Answers the examiner's recurring questions on the page itself:
  "where did the numbers come from?" -> sourced, page-cited characteristics
  "where are the laws?"              -> equations shown as maths
  "how did you get THIS number?"     -> laws with the current values plugged in
  "what does the point mean?"        -> a plain-language reading of the point
  "where is the twin?"               -> enter a real measured reading and see
                                        the gap to the manufacturer reference
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import pump

LINE = "#285A7A"      # steel blue — manufacturer reference line / active block
MODEL = "#C2703A"     # warm amber — model operating point
MEASURED = "#6A4C93"  # muted purple — a real reading you entered
INK = "#201E1A"
GRID = "#D7D1C4"
SHADE = "#B4553A"     # forbidden-zone tint


# ---------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------
def _kpi_row(r: pump.PumpResult) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Feed flow (m³/h)", f"{r.flow:.2f}",
              help="Delivered flow. Law: Q = rated flow × rpm/1500 × health "
                   "(Danfoss manual, p. 25).")
    c2.metric("Shaft power (kW)", f"{r.shaft_power:.2f}",
              help="Absorbed power. Equation: P = 16.7 × Q × p_out / 475 "
                   "(Danfoss manual, p. 26).")
    c3.metric("Volumetric efficiency (%)", f"{r.volumetric_efficiency*100:.1f}",
              help="Delivered flow divided by geometric flow "
                   "(displacement × rpm). A drop signals wear.")
    c4.metric("Specific energy (kWh/m³)", f"{r.specific_energy:.2f}",
              help="Shaft power divided by feed flow — energy to pump each "
                   "cubic metre of feed.")


# ---------------------------------------------------------------------
# Equations & sources
# ---------------------------------------------------------------------
def _equations_and_sources(r: pump.PumpResult) -> None:
    with st.expander("Equations, substitutions & sources", expanded=True):
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Laws used — with the current values plugged in**")
            st.latex(r.worked["rpm"])
            st.latex(r.worked["flow"])
            st.latex(r.worked["power"])
            st.latex(r.worked["eta"])
            st.latex(r.worked["sec"])
            st.caption(
                "Flow law from the Danfoss manual, p. 25 (flow is proportional "
                "to rpm). Power equation and the calc-factor 475 from p. 26. "
                "Frequency-to-speed ratio from the plant documentation "
                "(Chapter 4). The exact page for every value is in the table."
            )
        with right:
            st.markdown("**Characteristics — what each value is and where it comes from**")
            rows = [
                {"Parameter": k.replace("_", " "), "What it is": s.what,
                 "Value": f"{s.value:g}", "Unit": s.unit, "Source": s.source}
                for k, s in pump.CHARACTERISTICS.items()
            ]
            st.dataframe(
                pd.DataFrame(rows), hide_index=True, width='stretch',
                column_config={
                    "What it is": st.column_config.TextColumn(width="medium"),
                    "Source": st.column_config.TextColumn(width="large"),
                },
            )


# ---------------------------------------------------------------------
# Measured reading (optional, entered by hand — never assumed)
# ---------------------------------------------------------------------
def _measured_inputs() -> dict:
    with st.expander("Compare with a measured field reading (optional)", expanded=False):
        st.caption("Enter a real reading you took at the plant. Leave the fields "
                   "blank until you have one — nothing here is assumed or generated.")
        c1, c2, c3, c4 = st.columns(4)
        f = c1.number_input("Frequency (Hz)", value=None, min_value=0.0,
                            max_value=60.0, step=0.5, placeholder="—")
        q = c2.number_input("Feed flow (m³/h)", value=None, min_value=0.0,
                            step=0.1, placeholder="—")
        p = c3.number_input("Outlet pressure (bar)", value=None, min_value=0.0,
                            step=0.5, placeholder="—")
        w = c4.number_input("Shaft power (kW)", value=None, min_value=0.0,
                            step=0.1, placeholder="—")
    measured = {}
    if f is not None:
        measured["frequency_hz"] = f
    if q is not None:
        measured["flow"] = q
    if p is not None:
        measured["outlet_pressure"] = p
    if w is not None:
        measured["power"] = w
    return measured


# ---------------------------------------------------------------------
# Chart building blocks
# ---------------------------------------------------------------------
def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


def _envelope(field, lo, hi, dom):
    """Shaded forbidden zones beyond the manufacturer range + boundary rules."""
    below = alt.Chart(pd.DataFrame({"x": [dom[0]], "x2": [lo]})).mark_rect(
        color=SHADE, opacity=0.06).encode(
        x=alt.X("x:Q", scale=_xscale(dom)), x2="x2:Q")
    above = alt.Chart(pd.DataFrame({"x": [hi], "x2": [dom[1]]})).mark_rect(
        color=SHADE, opacity=0.06).encode(
        x=alt.X("x:Q", scale=_xscale(dom)), x2="x2:Q")
    rules = alt.Chart(pd.DataFrame({"x": [lo, hi]})).mark_rule(
        color=SHADE, strokeDash=[4, 4], opacity=0.5).encode(
        x=alt.X("x:Q", scale=_xscale(dom)))
    return [below, above, rules]


def _dot(df, x, y, color, shape, tips):
    return alt.Chart(df).mark_point(
        shape=shape, size=200, color=color, filled=True,
        stroke="#FFFFFF", strokeWidth=1.4,
    ).encode(x=alt.X(f"{x}:Q"), y=alt.Y(f"{y}:Q"), tooltip=tips)


def _style(layer, title):
    return (layer.properties(title=title, height=300)
            .configure(background="transparent")
            .configure_view(strokeWidth=0)
            .configure_title(color=INK, fontSize=15, anchor="start")
            .configure_axis(labelColor=INK, titleColor=INK, labelFontSize=12,
                            titleFontSize=13, gridColor=GRID, domainColor=INK,
                            tickColor=INK))


def _curve_flow(r, measured):
    dom = [660, 1540]
    ref = pd.DataFrame(pump.flow_reference(), columns=["rpm", "flow"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("rpm:Q", title="Speed (rpm)", scale=_xscale(dom)),
        y=alt.Y("flow:Q", title="Flow (m³/h)"))
    layers = _envelope("rpm", 700, 1500, dom) + [line]
    layers.append(_dot(pd.DataFrame([{"rpm": r.rpm, "flow": r.flow}]),
                       "rpm", "flow", MODEL, "circle",
                       [alt.Tooltip("rpm:Q", format=".0f", title="model rpm"),
                        alt.Tooltip("flow:Q", format=".2f", title="model flow")]))
    if measured.get("frequency_hz") and measured.get("flow"):
        mrpm = pump.rpm_from_frequency(measured["frequency_hz"])
        layers.append(_dot(pd.DataFrame([{"rpm": mrpm, "flow": measured["flow"]}]),
                           "rpm", "flow", MEASURED, "diamond",
                           [alt.Tooltip("rpm:Q", format=".0f", title="measured rpm"),
                            alt.Tooltip("flow:Q", format=".2f", title="measured flow")]))
    return _style(alt.layer(*layers), "Flow vs speed  ·  Danfoss p. 25")


def _curve_power(r, measured):
    dom = [26, 74]
    ref = pd.DataFrame(pump.power_reference(r.flow), columns=["pressure", "power"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("pressure:Q", title="Outlet pressure (bar)", scale=_xscale(dom)),
        y=alt.Y("power:Q", title="Shaft power (kW)"))
    layers = _envelope("pressure", 30, 70, dom) + [line]
    layers.append(_dot(pd.DataFrame([{"pressure": r.outlet_pressure, "power": r.shaft_power}]),
                       "pressure", "power", MODEL, "circle",
                       [alt.Tooltip("pressure:Q", format=".1f", title="model p_out"),
                        alt.Tooltip("power:Q", format=".2f", title="model power")]))
    if measured.get("outlet_pressure") and measured.get("power"):
        layers.append(_dot(pd.DataFrame([{"pressure": measured["outlet_pressure"],
                                          "power": measured["power"]}]),
                           "pressure", "power", MEASURED, "diamond",
                           [alt.Tooltip("pressure:Q", format=".1f", title="measured p_out"),
                            alt.Tooltip("power:Q", format=".2f", title="measured power")]))
    return _style(alt.layer(*layers), "Power vs pressure  ·  Danfoss p. 26")


# ---------------------------------------------------------------------
# Interpretation & assumptions
# ---------------------------------------------------------------------
def _interpretation(r, measured):
    st.markdown("**Reading the operating point**")
    render = {"ok": st.success, "warn": st.warning, "info": st.info}
    for level, text in pump.interpret(r, measured):
        render[level](text)


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **Steady state** — one settled operating point, no startup or transients.\n"
            "- **Positive-displacement** — flow is set by shaft speed and treated as "
            "independent of pressure.\n"
            "- **Efficiency** is bundled inside the manufacturer calc-factor (475); it "
            "is not modelled separately.\n"
            "- **Manufacturer reference is valid only within the Danfoss range** — "
            "700–1500 rpm and 30–70 bar. The shaded bands mark the outside.\n"
            "- **Not yet calibrated to this specific pump.** The line is the catalogue "
            "pump; calibration to your unit comes with the field measurements."
        )


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
def render(controls: dict, feed: dict) -> None:
    r = pump.simulate(
        frequency_hz=controls.get("frequency", 40.0),
        outlet_pressure=controls.get("outlet_pressure", 55.0),
        health_factor=controls.get("health_factor", 100.0) / 100.0,
        inlet_pressure=feed.get("suction", 3.0),
    )

    if r.warnings:
        st.warning("Outside the manufacturer envelope:  " + "  •  ".join(r.warnings))

    st.subheader("Key performance indicators")
    _kpi_row(r)

    st.divider()
    st.subheader("Where these numbers come from")
    _equations_and_sources(r)

    st.divider()
    st.subheader("Performance curves — pump vs Danfoss reference")
    measured = _measured_inputs()
    st.markdown(
        "**Legend** — :blue[━ line] Danfoss reference  ·  :orange[● amber] model "
        "point  ·  :violet[◆ purple] your measured reading  ·  shaded = outside "
        "the Danfoss range"
    )
    left, right = st.columns(2)
    left.altair_chart(_curve_flow(r, measured), theme=None, width='stretch')
    right.altair_chart(_curve_power(r, measured), theme=None, width='stretch')
    st.caption("The gap between a point and the line is the wear / lost-efficiency signal.")

    st.divider()
    _interpretation(r, measured)
    _assumptions()
