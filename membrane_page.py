"""Membrane-only view — same structure as the pump page.

Answers the examiner on the page itself: sourced parameters with their
page, the solution-diffusion laws shown with the current values plugged
in, a manufacturer/-book reference curve with the operating point, and a
place to drop a real measured reading and read the gap as a diagnosis.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import membrane as m

LINE = "#285A7A"      # steel blue — reference line / active block
MODEL = "#C2703A"     # warm amber — model operating point
MEASURED = "#6A4C93"  # muted purple — a real reading you entered
INK = "#201E1A"
GRID = "#D7D1C4"
SHADE = "#B4553A"


def _kpi_row(r: m.MembraneResult) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Permeate flow (m³/h)", f"{r.permeate_flow:.2f}",
              help="Qp = J × area / 1000.  J = Kw(T) × NDP  (IWA Ch. 9, p. 250).")
    c2.metric("Permeate flux (LMH)", f"{r.flux:.1f}",
              help="J = water permeability × net driving pressure.")
    c3.metric("Salt rejection (%)", f"{r.rejection*100:.2f}",
              help="1 − Cp/Cf, with Cp = Cfc·Ks(T)/J  (IWA Ch. 9, p. 252).")
    c4.metric("Recovery (%)", f"{r.recovery*100:.1f}",
              help="R = Qp / Qf (feed flow you entered).")

    d1, d2, d3, d4 = st.columns(4)
    ratio = (r.brine_flow / r.permeate_flow) if r.permeate_flow > 0 else float("inf")
    d1.metric("Brine flow Qc (m³/h)", f"{r.brine_flow:.2f}",
              help="Qc = Qf − Qp. Must stay above the 2.7 m³/h minimum (ESS).")
    d2.metric("Conc./perm. ratio", ("—" if ratio == float("inf") else f"{ratio:.1f}"),
              help="Qc / Qp. Should stay above 5:1 to keep polarisation in check.")
    d3.metric("Net driving pressure (bar)", f"{r.ndp:.1f}",
              help="NDP = feed pressure − ΔPe/2 − Δπ − permeate pressure.")
    d4.metric("Osmotic Δπ (bar)", f"{r.delta_pi:.1f}",
              help="Feed-concentrate osmotic pressure the pressure must overcome.")


def _equations_and_sources(r: m.MembraneResult) -> None:
    with st.expander("Equations, substitutions & sources", expanded=True):
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Laws used — with the current values plugged in**")
            st.latex(r.worked["cc"])
            st.latex(r.worked["ndp"])
            st.latex(r.worked["flux"])
            st.latex(r.worked["qp"])
            st.latex(r.worked["cp"])
            st.latex(r.worked["rej"])
            st.latex(r.worked["rec"])
            st.caption(
                "Single-element solution-diffusion model from IWA 2021, Chapter 9 "
                "(water flux, salt transport, osmotic build-up), solved by iteration "
                "on the recovery. Only the element-level laws are used; the book's "
                "72-element plant example is not. The exact page for every value is "
                "in the table."
            )
        with right:
            st.markdown("**Parameters — what each value is and where it comes from**")
            rows = [
                {"Parameter": k, "What it is": s.what,
                 "Value": f"{s.value:g}", "Unit": s.unit, "Source": s.source}
                for k, s in m.PARAMS.items()
            ]
            st.dataframe(
                pd.DataFrame(rows), hide_index=True, width='stretch',
                column_config={
                    "What it is": st.column_config.TextColumn(width="medium"),
                    "Source": st.column_config.TextColumn(width="large"),
                },
            )


def _measured_inputs() -> dict:
    with st.expander("Compare with a measured field reading (optional)", expanded=False):
        st.caption("Enter a real reading you took at the plant. Leave blank until you "
                   "have one — nothing here is assumed or generated.")
        c1, c2, c3, c4 = st.columns(4)
        pf = c1.number_input("Feed pressure (bar)", value=None, min_value=0.0,
                             step=0.5, placeholder="—")
        qp = c2.number_input("Permeate flow (m³/h)", value=None, min_value=0.0,
                             step=0.05, placeholder="—")
        cp = c3.number_input("Permeate TDS (mg/L)", value=None, min_value=0.0,
                             step=5.0, placeholder="—")
        tm = c4.number_input("Temperature (°C)", value=None, min_value=0.0,
                             step=0.5, placeholder="—")
    out = {}
    if pf is not None:
        out["feed_pressure"] = pf
    if qp is not None:
        out["permeate_flow"] = qp
    if cp is not None:
        out["permeate_tds"] = cp
    if tm is not None:
        out["temperature"] = tm
    return out


def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


def _envelope(lo_forbidden, dom):
    band = alt.Chart(pd.DataFrame({"x": [lo_forbidden], "x2": [dom[1]]})).mark_rect(
        color=SHADE, opacity=0.06).encode(
        x=alt.X("x:Q", scale=_xscale(dom)), x2="x2:Q")
    rule = alt.Chart(pd.DataFrame({"x": [lo_forbidden]})).mark_rule(
        color=SHADE, strokeDash=[4, 4], opacity=0.5).encode(
        x=alt.X("x:Q", scale=_xscale(dom)))
    return [band, rule]


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


def _curve_flux(r, feed, measured):
    dom = [30, 85]
    ref = pd.DataFrame(m.flux_reference(feed["tds"], feed["temperature"],
                                        feed["feed_flow"], r.fouling),
                       columns=["pressure", "flux"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("pressure:Q", title="Feed pressure (bar)", scale=_xscale(dom)),
        y=alt.Y("flux:Q", title="Flux (LMH)"))
    layers = _envelope(m.ENVELOPE["max_pressure"][0], dom) + [line]
    layers.append(_dot(pd.DataFrame([{"pressure": r.feed_pressure, "flux": r.flux}]),
                       "pressure", "flux", MODEL, "circle",
                       [alt.Tooltip("pressure:Q", format=".1f", title="model p_feed"),
                        alt.Tooltip("flux:Q", format=".1f", title="model flux")]))
    if measured.get("feed_pressure") and measured.get("permeate_flow"):
        jm = measured["permeate_flow"] * 1000.0 / m.p("area")
        layers.append(_dot(pd.DataFrame([{"pressure": measured["feed_pressure"], "flux": jm}]),
                           "pressure", "flux", MEASURED, "diamond",
                           [alt.Tooltip("pressure:Q", format=".1f", title="measured p_feed"),
                            alt.Tooltip("flux:Q", format=".1f", title="measured flux")]))
    return _style(alt.layer(*layers), "Flux vs feed pressure  ·  IWA Ch. 9")


def _curve_rejection(r, feed, measured):
    dom = [30, 85]
    data = [(pf, rj) for pf, rj in m.rejection_reference(
        feed["tds"], feed["temperature"], feed["feed_flow"], r.fouling) if rj is not None]
    ref = pd.DataFrame(data, columns=["pressure", "rejection"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("pressure:Q", title="Feed pressure (bar)", scale=_xscale(dom)),
        y=alt.Y("rejection:Q", title="Salt rejection (%)",
                scale=alt.Scale(zero=False)))
    layers = _envelope(m.ENVELOPE["max_pressure"][0], dom) + [line]
    layers.append(_dot(pd.DataFrame([{"pressure": r.feed_pressure, "rejection": r.rejection*100}]),
                       "pressure", "rejection", MODEL, "circle",
                       [alt.Tooltip("pressure:Q", format=".1f", title="model p_feed"),
                        alt.Tooltip("rejection:Q", format=".2f", title="model rejection %")]))
    if measured.get("feed_pressure") and measured.get("permeate_tds") and feed["tds"] > 0:
        rj = (1 - measured["permeate_tds"] / feed["tds"]) * 100.0
        layers.append(_dot(pd.DataFrame([{"pressure": measured["feed_pressure"], "rejection": rj}]),
                           "pressure", "rejection", MEASURED, "diamond",
                           [alt.Tooltip("pressure:Q", format=".1f", title="measured p_feed"),
                            alt.Tooltip("rejection:Q", format=".2f", title="measured rejection %")]))
    return _style(alt.layer(*layers), "Salt rejection vs feed pressure  ·  IWA Ch. 9")


def _curve_flux_vs_temp(r, feed):
    dom = [15, 42]
    ref = pd.DataFrame(m.flux_vs_temperature(r.feed_pressure, feed["tds"],
                                             feed["feed_flow"], r.fouling),
                       columns=["temp", "flux"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("temp:Q", title="Feed temperature (°C)", scale=_xscale(dom)),
        y=alt.Y("flux:Q", title="Flux (LMH)"))
    dot = _dot(pd.DataFrame([{"temp": feed["temperature"], "flux": r.flux}]),
               "temp", "flux", MODEL, "circle",
               [alt.Tooltip("temp:Q", format=".1f", title="temp"),
                alt.Tooltip("flux:Q", format=".1f", title="flux")])
    return _style(alt.layer(line, dot), "Flux vs feed temperature  (≈3%/°C)")


def _curve_flux_vs_salinity(r, feed):
    dom = [30000, 50000]
    ref = pd.DataFrame(m.flux_vs_salinity(r.feed_pressure, feed["temperature"],
                                          feed["feed_flow"], r.fouling),
                       columns=["tds", "flux"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("tds:Q", title="Feed TDS (mg/L)", scale=_xscale(dom),
                axis=alt.Axis(format=",.0f")),
        y=alt.Y("flux:Q", title="Flux (LMH)"))
    dot = _dot(pd.DataFrame([{"tds": feed["tds"], "flux": r.flux}]),
               "tds", "flux", MODEL, "circle",
               [alt.Tooltip("tds:Q", format=",.0f", title="feed TDS"),
                alt.Tooltip("flux:Q", format=".1f", title="flux")])
    return _style(alt.layer(line, dot), "Flux vs feed salinity")


def _interpretation(r, measured):
    st.markdown("**Reading the operating point**")
    render = {"ok": st.success, "warn": st.warning, "info": st.info}
    for level, text in m.interpret(r, measured):
        render[level](text)


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **Steady state**, and **one lumped element** — the average feed-concentrate "
            "concentration is used rather than resolving along the element.\n"
            "- **Seawater single element**: the plant is one element, so only the "
            "element-level laws are used, not the book's multi-element plant example.\n"
            "- **Osmotic pressure** from the 0.8 bar / 1000 mg/L rule of thumb; can be "
            "replaced by a seawater correlation later.\n"
            "- **Concentration polarisation (β)** is reported as a check only; its effect "
            "on the driving pressure is neglected in this first version.\n"
            "- **Kw and Ks** start from the values the book derives from the element test; "
            "they are **not yet calibrated to our element** (the ESS notes ±15 % variation "
            "between elements). Calibration comes from the field measurements.\n"
            "- **Temperature correction** is ~3 % per °C."
        )


def render(controls: dict, feed: dict) -> None:
    r = m.simulate(
        feed_pressure=controls.get("feed_pressure", 55.0),
        feed_tds=feed.get("tds", 41000.0),
        temperature=feed.get("temperature", 28.0),
        feed_flow=feed.get("feed_flow", 10.5),
        fouling=controls.get("fouling", 100.0) / 100.0,
    )

    if not r.converged:
        st.warning("The recovery iteration did not settle — check the feed flow and pressure.")
    if r.warnings:
        st.warning("Outside the element envelope:  " + "  •  ".join(r.warnings))

    st.subheader("Key performance indicators")
    _kpi_row(r)

    st.divider()
    st.subheader("Where these numbers come from")
    _equations_and_sources(r)

    st.divider()
    st.subheader("Performance curves — element vs reference")
    measured = _measured_inputs()
    st.markdown(
        "**Legend** — :blue[━ line] book/ESS reference  ·  :orange[● amber] model "
        "point  ·  :violet[◆ purple] your measured reading  ·  shaded = above the "
        "element's max pressure"
    )
    a1, a2 = st.columns(2)
    a1.altair_chart(_curve_flux(r, feed, measured), theme=None, width='stretch')
    a2.altair_chart(_curve_rejection(r, feed, measured), theme=None, width='stretch')
    st.caption("Flux rises only once the feed pressure beats the osmotic pressure; the gap "
               "between a point and the line is the fouling / ageing signal.")

    st.markdown("**Sensitivity to the feed conditions you measure** — the amber dot is the "
                "current point; these help you read and normalise field data.")
    b1, b2 = st.columns(2)
    b1.altair_chart(_curve_flux_vs_temp(r, feed), theme=None, width='stretch')
    b2.altair_chart(_curve_flux_vs_salinity(r, feed), theme=None, width='stretch')

    st.divider()
    _interpretation(r, measured)
    _assumptions()
