"""Valve-only view — corrected (back-pressure) framing.

The brine globe valve is a variable resistance: it must pass the brine the
membrane rejects, and in doing so it develops a back-pressure that sets the
recovery. Inputs are the opening and the brine flow; the output is the
back-pressure. The page is about calibrating the representative curve.
"""
from __future__ import annotations

import math

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
RATING = V.ENVELOPE["max_pressure"][0]


def _fmt(x, nd=1):
    return "∞" if not math.isfinite(x) else f"{x:.{nd}f}"


def _kpi_row(r: V.ValveResult) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Back-pressure ΔP (bar)", _fmt(r.delta_p),
              help="ΔP = (Q / (0.865·Cv))²·SG. This sets the system pressure and the recovery.")
    c2.metric("Cv at this opening", f"{r.cv:.2f}",
              help="Equal-% characteristic: Cv = Cv_max · R^(x−1).")
    c3.metric("Valve resistance", _fmt(r.resistance, 2),
              help="R in ΔP = R·Q². Rises steeply as you close the valve.")
    c4.metric("Flow condition", "Cavitating" if r.cavitating else "OK",
              help="Cavitates when the back-pressure exceeds the FL-based onset.")


def _equations_and_sources(r: V.ValveResult) -> None:
    with st.expander("Equations, substitutions & sources", expanded=True):
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Laws used — with the current values plugged in**")
            st.latex(r.worked["cv"])
            st.latex(r.worked["dp"])
            st.caption(
                "The valve is a variable resistance: the Cv equation Q = Cv·√(ΔP/SG) "
                "is solved for the back-pressure ΔP it must develop to pass the brine "
                "flow the membrane rejects. Opening sets Cv through the equal-% "
                "characteristic. Cv and the shape are representative — the real curve "
                "comes from calibration."
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
        st.caption("Enter a real reading from the plant — a hand-wheel position with the "
                   "brine flow it passes and the back-pressure. Leave blank until you have one.")
        c1, c2, c3 = st.columns(3)
        op = c1.number_input("Valve opening (% travel)", value=None, min_value=0.0,
                            max_value=100.0, step=1.0, placeholder="—")
        qb = c2.number_input("Brine flow (m³/h)", value=None, min_value=0.0,
                            step=0.1, placeholder="—")
        dp = c3.number_input("Back-pressure (bar)", value=None, min_value=0.0,
                            step=0.5, placeholder="—")
    out = {}
    if op is not None:
        out["opening"] = op
    if qb is not None:
        out["brine_flow"] = qb
    if dp is not None:
        out["back_pressure"] = dp
    return out


def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


def _yscale(dom):
    return alt.Scale(domain=dom, nice=False, clamp=True)


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


def _overpressure_band(ydom):
    """Shade the region above the Class 600 rating."""
    band = alt.Chart(pd.DataFrame({"y": [RATING], "y2": [ydom[1]]})).mark_rect(
        color=SHADE, opacity=0.07).encode(y=alt.Y("y:Q"), y2="y2:Q")
    rule = alt.Chart(pd.DataFrame({"y": [RATING]})).mark_rule(
        color=SHADE, strokeDash=[4, 4], opacity=0.6).encode(y=alt.Y("y:Q"))
    return [band, rule]


def _curve_char(r, measured):
    xdom, ydom = [12, 100], [0, 110]
    data = [(o, d) for o, d in V.bp_vs_opening(r.brine_flow, r.sg, lo=xdom[0]) if d is not None]
    ref = pd.DataFrame(data, columns=["opening", "dp"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("opening:Q", title="Valve opening (% travel)", scale=_xscale(xdom)),
        y=alt.Y("dp:Q", title="Back-pressure (bar)", scale=_yscale(ydom)))
    layers = _overpressure_band(ydom) + [line]
    if math.isfinite(r.delta_p):
        layers.append(_dot(pd.DataFrame([{"opening": r.opening, "dp": r.delta_p}]),
                           "opening", "dp", MODEL, "circle",
                           [alt.Tooltip("opening:Q", format=".0f", title="opening %"),
                            alt.Tooltip("dp:Q", format=".1f", title="back-pressure")]))
    if measured.get("opening") is not None and measured.get("back_pressure"):
        layers.append(_dot(pd.DataFrame([{"opening": measured["opening"],
                                          "dp": measured["back_pressure"]}]),
                           "opening", "dp", MEASURED, "diamond",
                           [alt.Tooltip("opening:Q", format=".0f", title="measured opening"),
                            alt.Tooltip("dp:Q", format=".1f", title="measured ΔP")]))
    return _style(alt.layer(*layers), "Back-pressure vs opening  ·  representative")


def _curve_q(r):
    xdom, ydom = [0, 15], [0, 110]
    data = [(q, d) for q, d in V.bp_vs_brineflow(r.opening, r.sg, lo=xdom[0], hi=xdom[1]) if d is not None]
    ref = pd.DataFrame(data, columns=["q", "dp"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3).encode(
        x=alt.X("q:Q", title="Brine flow (m³/h)", scale=_xscale(xdom)),
        y=alt.Y("dp:Q", title="Back-pressure (bar)", scale=_yscale(ydom)))
    layers = _overpressure_band(ydom) + [line]
    if math.isfinite(r.delta_p):
        layers.append(_dot(pd.DataFrame([{"q": r.brine_flow, "dp": r.delta_p}]),
                           "q", "dp", MODEL, "circle",
                           [alt.Tooltip("q:Q", format=".2f", title="brine flow"),
                            alt.Tooltip("dp:Q", format=".1f", title="back-pressure")]))
    return _style(alt.layer(*layers), "Back-pressure vs brine flow  (ΔP = R·Q², at this opening)")


def _interpretation(r, measured):
    st.markdown("**Reading the operating point**")
    render = {"ok": st.success, "warn": st.warning, "info": st.info}
    for level, text in V.interpret(r, measured):
        render[level](text)


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **The valve is a resistance**: inputs are the opening and the brine flow "
            "it must pass; the output is the back-pressure it develops.\n"
            "- **Equal-percentage characteristic** assumed (globe inherent); the real "
            "curve comes from calibration.\n"
            "- **Cv_max is representative** for a 1½″ globe valve — a manual BS 1873 "
            "valve has no published curve.\n"
            "- **Opening = fraction of hand-wheel travel** (manual valve).\n"
            "- The brine **discharges to ~atmosphere**, so the back-pressure is the "
            "upstream brine pressure.\n"
            "- **Fully open → ~0 back-pressure** → the system cannot build pressure and "
            "produces nothing; the throttling is what makes the RO work.\n"
            "- At operating pressures the valve **cavitates** (CF8M is chosen for the erosion).\n"
            "- Brine specific gravity ≈ 1.03."
        )


def render(controls: dict, feed: dict) -> None:
    r = V.simulate(
        opening_pct=controls.get("valve_opening", 60.0),
        brine_flow=controls.get("brine_flow", 9.5),
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
        "point  ·  :violet[◆ purple] your measured reading  ·  shaded = above the "
        "Class 600 rating"
    )
    a1, a2 = st.columns(2)
    a1.altair_chart(_curve_char(r, measured), theme=None, width='stretch')
    a2.altair_chart(_curve_q(r), theme=None, width='stretch')
    st.caption("Open the valve → back-pressure falls toward zero; close it → it climbs "
               "(and can exceed the valve rating). Enter a measured point to fit the real curve.")

    st.divider()
    _interpretation(r, measured)
    _assumptions()
