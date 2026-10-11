"""Valve-only view — same structure as the pump and membrane pages.

The brine globe valve is a manual throttle with no published Cv curve, so
this page is really about calibration: a representative equal-% curve, the
flow law, and a place to drop a measured (hand-wheel position, ΔP, brine
flow) reading to fit the real characteristic.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import valve as V

LINE = "#285A7A"
MODEL = "#C2703A"
MEASURED = "#6A4C93"
INK = "#201E1A"
GRID = "#D7D1C4"
SHADE = "#B4553A"


def _choke_onset() -> float:
    """ΔP above which the valve cavitates (derived from the choke condition)."""
    fl = V.v("FL")
    return fl ** 2 * (V.P_ATM - V.FF * V.PV) / (1.0 - fl ** 2)


def _kpi_row(r: V.ValveResult) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Brine flow Qb (m³/h)", f"{r.brine_flow:.2f}",
              help="Q = 0.865 · Cv · √(ΔP_eff / SG).")
    c2.metric("Cv at this opening", f"{r.cv:.2f}",
              help="Equal-% characteristic: Cv = Cv_max · R^(x−1).")
    c3.metric("Effective ΔP (bar)", f"{r.dp_eff:.1f}",
              help="Pressure drop actually driving flow (capped by the choke limit).")
    c4.metric("Flow condition", "Cavitating" if r.choked else "OK",
              help="Choked flow when ΔP exceeds the FL-based choke limit.")


def _equations_and_sources(r: V.ValveResult) -> None:
    with st.expander("Equations, substitutions & sources", expanded=True):
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Laws used — with the current values plugged in**")
            st.latex(r.worked["cv"])
            st.latex(r.worked["choke"])
            st.latex(r.worked["q"])
            st.caption(
                "Liquid flow through a control valve, Q = Cv·√(ΔP/SG) with an "
                "equal-percentage characteristic and an FL-based choke limit "
                "(standard control-valve references). The valve discharges to "
                "~atmosphere, so ΔP is the upstream brine pressure. Cv and the "
                "characteristic are representative — the real curve comes from "
                "calibration."
            )
        with right:
            st.markdown("**Parameters — what each value is and where it comes from**")
            rows = [
                {"Parameter": k, "What it is": s.what,
                 "Value": f"{s.value:g}", "Unit": s.unit, "Source": s.source}
                for k, s in V.PARAMS.items()
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
        st.caption("Enter a real reading from the plant — a hand-wheel position with "
                   "its brine flow and pressure drop. Leave blank until you have one.")
        c1, c2, c3 = st.columns(3)
        op = c1.number_input("Valve opening (% travel)", value=None, min_value=0.0,
                            max_value=100.0, step=1.0, placeholder="—")
        dp = c2.number_input("Pressure drop (bar)", value=None, min_value=0.0,
                            step=0.5, placeholder="—")
        qb = c3.number_input("Brine flow (m³/h)", value=None, min_value=0.0,
                            step=0.1, placeholder="—")
    out = {}
    if op is not None:
        out["opening"] = op
    if dp is not None:
        out["delta_p"] = dp
    if qb is not None:
        out["brine_flow"] = qb
    return out


def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


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


def _curve_char(r, measured):
    dom = [0, 100]
    ref = pd.DataFrame(V.flow_vs_opening(r.delta_p, r.sg), columns=["opening", "flow"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("opening:Q", title="Valve opening (% travel)", scale=_xscale(dom)),
        y=alt.Y("flow:Q", title="Brine flow (m³/h)"))
    layers = [line, _dot(pd.DataFrame([{"opening": r.opening, "flow": r.brine_flow}]),
                         "opening", "flow", MODEL, "circle",
                         [alt.Tooltip("opening:Q", format=".0f", title="opening %"),
                          alt.Tooltip("flow:Q", format=".2f", title="brine flow")])]
    if measured.get("opening") is not None and measured.get("brine_flow"):
        layers.append(_dot(pd.DataFrame([{"opening": measured["opening"],
                                          "flow": measured["brine_flow"]}]),
                           "opening", "flow", MEASURED, "diamond",
                           [alt.Tooltip("opening:Q", format=".0f", title="measured opening"),
                            alt.Tooltip("flow:Q", format=".2f", title="measured flow")]))
    return _style(alt.layer(*layers), "Brine flow vs opening (equal-%)  ·  representative")


def _curve_dp(r):
    dom = [0, 80]
    onset = _choke_onset()
    ref = pd.DataFrame(V.flow_vs_dp(r.opening, r.sg, lo=dom[0], hi=dom[1]),
                       columns=["dp", "flow"])
    band = alt.Chart(pd.DataFrame({"x": [onset], "x2": [dom[1]]})).mark_rect(
        color=SHADE, opacity=0.06).encode(x=alt.X("x:Q", scale=_xscale(dom)), x2="x2:Q")
    rule = alt.Chart(pd.DataFrame({"x": [onset]})).mark_rule(
        color=SHADE, strokeDash=[4, 4], opacity=0.5).encode(x=alt.X("x:Q", scale=_xscale(dom)))
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("dp:Q", title="Pressure drop (bar)", scale=_xscale(dom)),
        y=alt.Y("flow:Q", title="Brine flow (m³/h)"))
    dot = _dot(pd.DataFrame([{"dp": r.delta_p, "flow": r.brine_flow}]), "dp", "flow",
               MODEL, "circle",
               [alt.Tooltip("dp:Q", format=".1f", title="ΔP"),
                alt.Tooltip("flow:Q", format=".2f", title="brine flow")])
    return _style(alt.layer(band, rule, line, dot),
                  "Brine flow vs ΔP  (shaded = cavitating region)")


def _interpretation(r, measured):
    st.markdown("**Reading the operating point**")
    render = {"ok": st.success, "warn": st.warning, "info": st.info}
    for level, text in V.interpret(r, measured):
        render[level](text)


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **Equal-percentage characteristic** assumed (globe inherent); the real "
            "curve comes from calibration.\n"
            "- **Cv_max is representative** for a 1½″ globe valve — a manual BS 1873 "
            "valve has no published Cv curve.\n"
            "- **Opening = fraction of hand-wheel travel** (manual valve); on site, "
            "record the number of turns.\n"
            "- The brine **discharges to ~atmosphere**, so ΔP ≈ the upstream brine pressure.\n"
            "- **Choked flow** uses a representative FL; at operating pressures the valve "
            "cavitates — the body is CF8M stainless for exactly this erosion.\n"
            "- The valve is **oversized for the duty** (Cv_max ≫ the ~1.5 Cv needed), so "
            "it runs near the bottom of its travel.\n"
            "- Brine specific gravity ≈ 1.03."
        )


def render(controls: dict, feed: dict) -> None:
    r = V.simulate(
        opening_pct=controls.get("valve_opening", 60.0),
        delta_p=controls.get("valve_dp", 50.0),
    )

    if r.warnings:
        st.warning("Note:  " + "  •  ".join(r.warnings))

    st.subheader("Key performance indicators")
    _kpi_row(r)

    st.divider()
    st.subheader("Where these numbers come from")
    _equations_and_sources(r)

    st.divider()
    st.subheader("Characteristic — representative, to be calibrated")
    measured = _measured_inputs()
    st.markdown(
        "**Legend** — :blue[━ line] representative curve  ·  :orange[● amber] model "
        "point  ·  :violet[◆ purple] your measured reading  ·  shaded = cavitating region"
    )
    a1, a2 = st.columns(2)
    a1.altair_chart(_curve_char(r, measured), theme=None, width='stretch')
    a2.altair_chart(_curve_dp(r), theme=None, width='stretch')
    st.caption("Enter a measured point to fit Cv_max and the characteristic to your "
               "actual valve — the line is only a representative starting shape.")

    st.divider()
    _interpretation(r, measured)
    _assumptions()
