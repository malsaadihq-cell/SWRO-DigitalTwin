"""Valve-only view — the brine valve described by its measured resistance.

The brine globe valve is a variable resistance: it must pass the brine the
membrane rejects, and in doing so it develops a back-pressure P_b = K·Q².
The hand-wheel position is never measured, so the valve is described by its
effect, K, which any steady reading gives directly (K = P_b / Q²).
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

# Measured runs (brine flow m³/h, brine-gauge pressure bar) — Exp 1–9, all at 60 Hz
EXP_POINTS = [
    ("Exp 1", 13.00, 50.33), ("Exp 2", 18.00, 34.47), ("Exp 3", 14.00, 36.54),
    ("Exp 4", 13.75, 41.37), ("Exp 5", 13.25, 47.57), ("Exp 6", 12.50, 55.85),
    ("Exp 7", 13.25, 60.33), ("Exp 8", 14.00, 33.09), ("Exp 9", 13.50, 42.06),
]


def _fmt(x, nd=1):
    return "∞" if not math.isfinite(x) else f"{x:.{nd}f}"


def _kpi_row(r: V.ValveResult) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Back-pressure P_b (bar)", _fmt(r.delta_p, 2),
              help="P_b = K·Q². This is the brine-gauge pressure; it sets the system "
                   "pressure and the recovery.")
    c2.metric("Resistance K (bar per (m³/h)²)", f"{r.resistance:.3f}",
              help="The hand-wheel setting expressed by its effect: K = P_b / Q².")
    c3.metric("Equivalent Cv (information)", _fmt(r.cv_equivalent, 2),
              help="K expressed as a flow coefficient, Cv = √(SG/K)/0.865 — only for "
                   "comparison with valve catalogues; not used in any calculation.")


def _equations_and_sources(r: V.ValveResult) -> None:
    with st.expander("Equations, substitutions & sources", expanded=True):
        left, right = st.columns([1, 1])
        with left:
            st.markdown("**Law used — with the current values plugged in**")
            st.latex(r.worked["dp"])
            st.latex(r.worked["k"])
            st.latex(r.worked["cv"])
            st.caption(
                "The valve passes the brine the membrane rejects and develops the "
                "back-pressure P_b = K·Q². K is measured, not assumed: the hand-wheel "
                "position is not recorded, so there is no opening %, Cv curve or "
                "cavitation model. P ∝ Q² holds for a throttling valve whether the flow "
                "is choked or not, so K carries all of that in one measured number.")
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


def _measured_runs() -> None:
    with st.expander("Measured resistance of each experiment (Exp 1–9)", expanded=False):
        df = pd.DataFrame([{
            "Run": n, "Brine flow (m³/h)": f"{q:.2f}", "Brine pressure (bar)": f"{p:.2f}",
            "K = P/Q²": f"{V.resistance_from_reading(p, q):.3f}",
        } for n, q, p in EXP_POINTS])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("Each run was a different, unrecorded hand-wheel position, so each has "
                   "its own K. To test the law P = K·Q²: keep the hand-wheel still, change "
                   "the VFD frequency, and K should stay roughly constant.")


def _measured_inputs() -> dict:
    with st.expander("Get K from a reading (optional)", expanded=False):
        st.caption("Enter a steady reading from the plant — the brine flow and the brine "
                   "gauge pressure. Leave blank until you have one.")
        c1, c2 = st.columns(2)
        qb = c1.number_input("Brine flow (m³/h)", value=None, min_value=0.0,
                             step=0.1, placeholder="—")
        dp = c2.number_input("Brine pressure (bar)", value=None, min_value=0.0,
                             step=0.5, placeholder="—")
    out = {}
    if qb is not None:
        out["brine_flow"] = qb
    if dp is not None:
        out["back_pressure"] = dp
    return out


def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


def _yscale(dom):
    return alt.Scale(domain=dom, nice=False, clamp=False)


def _dot(df, x, y, color, shape, tips, size=200):
    return alt.Chart(df).mark_point(
        shape=shape, size=size, color=color, filled=True,
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


def _band(ydom):
    over = alt.Chart(pd.DataFrame({"y": [RATING], "y2": [ydom[1]]})).mark_rect(
        color=SHADE, opacity=0.07).encode(y=alt.Y("y:Q"), y2="y2:Q")
    rule = alt.Chart(pd.DataFrame({"y": [RATING]})).mark_rule(
        color=SHADE, strokeDash=[4, 4], opacity=0.6).encode(y=alt.Y("y:Q"))
    return [over, rule]


def _curve_q(r, measured):
    xdom, ydom = [0, 20], [0, 110]
    ref = pd.DataFrame(V.bp_vs_brineflow(r.resistance, lo=xdom[0], hi=xdom[1]),
                       columns=["q", "dp"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3, clip=True).encode(
        x=alt.X("q:Q", title="Brine flow (m³/h)", scale=_xscale(xdom)),
        y=alt.Y("dp:Q", title="Back-pressure (bar)", scale=_yscale(ydom)))
    exp = pd.DataFrame([{"q": q, "dp": p, "run": n} for n, q, p in EXP_POINTS])
    layers = _band(ydom) + [line,
        _dot(exp, "q", "dp", "#8A8578", "circle",
             [alt.Tooltip("run:N"), alt.Tooltip("q:Q", format=".2f", title="brine flow"),
              alt.Tooltip("dp:Q", format=".1f", title="brine pressure")], size=70),
        _dot(pd.DataFrame([{"q": r.brine_flow, "dp": r.delta_p}]), "q", "dp", MODEL, "circle",
             [alt.Tooltip("q:Q", format=".2f", title="brine flow"),
              alt.Tooltip("dp:Q", format=".1f", title="back-pressure")])]
    if measured.get("brine_flow") and measured.get("back_pressure") is not None:
        layers.append(_dot(pd.DataFrame([{"q": measured["brine_flow"],
                                          "dp": measured["back_pressure"]}]),
                           "q", "dp", MEASURED, "diamond",
                           [alt.Tooltip("q:Q", format=".2f", title="measured flow"),
                            alt.Tooltip("dp:Q", format=".1f", title="measured pressure")]))
    return _style(alt.layer(*layers), "Back-pressure vs brine flow at this K  (P = K·Q²)")


def _curve_k(r):
    xdom, ydom = [0.05, 1.0], [0, 110]
    ref = pd.DataFrame(V.bp_vs_resistance(r.brine_flow, lo=xdom[0], hi=xdom[1]),
                       columns=["k", "dp"])
    line = alt.Chart(ref).mark_line(color=LINE, strokeWidth=3, clip=True).encode(
        x=alt.X("k:Q", title="Resistance K (bar per (m³/h)²)", scale=_xscale(xdom)),
        y=alt.Y("dp:Q", title="Back-pressure (bar)", scale=_yscale(ydom)))
    layers = _band(ydom) + [line,
        _dot(pd.DataFrame([{"k": r.resistance, "dp": r.delta_p}]), "k", "dp", MODEL, "circle",
             [alt.Tooltip("k:Q", format=".3f", title="K"),
              alt.Tooltip("dp:Q", format=".1f", title="back-pressure")])]
    return _style(alt.layer(*layers), "Back-pressure vs K at this brine flow")


def _interpretation(r, measured):
    st.markdown("**Reading the operating point**")
    render = {"ok": st.success, "warn": st.warning, "info": st.info}
    for level, text in V.interpret(r, measured):
        render[level](text)


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **The valve is a resistance**: inputs are K and the brine flow it must "
            "pass; the output is the back-pressure P_b = K·Q².\n"
            "- **K is measured, not assumed.** The hand-wheel is turned by hand and its "
            "position is not recorded, so no opening %, Cv curve, trim characteristic or "
            "pressure-recovery factor is used.\n"
            "- **P ∝ Q² at a fixed hand-wheel position** — to be confirmed by holding the "
            "valve still and changing the VFD frequency (K should stay constant).\n"
            "- The brine **discharges to ~atmosphere**, so the back-pressure is the brine "
            "gauge pressure.\n"
            "- The valve throttles 30–60 bar across one seat, so **cavitation is expected** "
            "(CF8M body). It is a wear note, not part of the calculation.\n"
            "- Equivalent Cv is shown only for comparison with catalogues.")


def render(controls: dict, feed: dict) -> None:
    r = V.simulate(
        resistance=controls.get("valve_resistance", V.v("K_ref")),
        brine_flow=controls.get("brine_flow", 13.5),
    )

    if r.warnings:
        st.warning("Note:  " + "  •  ".join(r.warnings))

    st.subheader("Key performance indicators")
    _kpi_row(r)

    st.divider()
    st.subheader("Where these numbers come from")
    _equations_and_sources(r)
    _measured_runs()

    st.divider()
    st.subheader("Characteristic")
    measured = _measured_inputs()
    st.markdown(
        "**Legend** — :blue[━ line] P = K·Q² at the current K  ·  :orange[● amber] current "
        "point  ·  grey dots = Exp 1–9 (each at its own hand-wheel position)  ·  "
        ":violet[◆ purple] your reading  ·  shaded = above the Class 600 rating"
    )
    a1, a2 = st.columns(2)
    a1.altair_chart(_curve_q(r, measured), theme=None, width='stretch')
    a2.altair_chart(_curve_k(r), theme=None, width='stretch')
    st.caption("Close the valve → K rises → the back-pressure climbs for the same brine flow. "
               "A grey dot lies on the line only when K equals that run's own K.")

    st.divider()
    _interpretation(r, measured)
    _assumptions()
