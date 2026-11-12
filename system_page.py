"""Full-system view — the coupled plant, run like a real operation.

Two knobs (VFD frequency, brine-valve resistance K) + the measured feed
conditions drive the whole plant. The page reports the four project KPIs
(recovery, flux, rejection, SEC), the stream states, the coupling, and
performance maps across the knobs.
"""
from __future__ import annotations

import math

import altair as alt
import pandas as pd
import streamlit as st

from core import system as S

LINE = "#285A7A"
MODEL = "#C2703A"
INK = "#201E1A"
GRID = "#D7D1C4"


def _fmt(x, nd=2):
    return "—" if (x is None or not math.isfinite(x)) else f"{x:.{nd}f}"


def _kpis(r: S.SystemResult) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recovery (%)", _fmt(r.recovery * 100, 1),
              help="R = permeate / feed flow. Set mainly by the valve resistance K.")
    c2.metric("Permeate flux (LMH)", _fmt(r.flux, 1),
              help="Permeate flow per membrane area.")
    c3.metric("Salt rejection (%)", _fmt(r.rejection * 100, 2),
              help="1 − permeate TDS / feed TDS.")
    c4.metric("Specific energy (kWh/m³)", _fmt(r.sec, 1),
              help="Pump shaft power / permeate flow — the key energy KPI.")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Operating pressure (bar)", _fmt(r.operating_pressure, 1),
              help="Feed-gauge pressure, solved from the pump–membrane–valve balance.")
    d2.metric("Feed flow (m³/h)", _fmt(r.feed_flow, 2),
              help="Delivered by the pump from the VFD frequency.")
    d3.metric("Permeate flow (m³/h)", _fmt(r.permeate_flow, 2))
    d4.metric("Shaft power (kW)", _fmt(r.power, 2))


def _streams(r: S.SystemResult) -> None:
    st.markdown("**Stream states**")
    df = pd.DataFrame([
        {"Stream": "Feed", "Flow (m³/h)": f"{r.feed_flow:.2f}",
         "Pressure (bar)": f"{r.operating_pressure:.1f}", "TDS (mg/L)": f"{r.feed_tds:.0f}"},
        {"Stream": "Permeate", "Flow (m³/h)": f"{r.permeate_flow:.2f}",
         "Pressure (bar)": "~0", "TDS (mg/L)": f"{r.permeate_tds:.0f}"},
        {"Stream": "Brine", "Flow (m³/h)": f"{r.brine_flow:.2f}",
         "Pressure (bar)": _fmt(r.valve_back_pressure, 1),
         "TDS (mg/L)": f"{r.brine_tds:.0f}"},
    ])
    st.dataframe(df, hide_index=True, width='stretch')


def _coupling(r: S.SystemResult) -> None:
    with st.expander("How the plant is solved (coupling)", expanded=False):
        st.caption("The three blocks share one unknown — the operating pressure. The pump "
                   "fixes the feed flow; the membrane turns part of it into permeate; the valve "
                   "must pass the brine and develops the back-pressure K·Qb². One pressure "
                   "balances all, with the measured gauge-to-gauge loss ΔP_gauges in between.")
        st.latex(r.worked["qfeed"])
        st.latex(r.worked["balance"])
        st.latex(r.worked["pressure"])
        st.latex(r.worked["brine_p"])
        st.latex(r.worked["recovery"])
        st.latex(r.worked["sec"])


def _xscale(dom):
    return alt.Scale(domain=dom, nice=False)


def _style(layer, title):
    return (layer.properties(title=title, height=280)
            .configure(background="transparent").configure_view(strokeWidth=0)
            .configure_title(color=INK, fontSize=14, anchor="start")
            .configure_axis(labelColor=INK, titleColor=INK, labelFontSize=11,
                            titleFontSize=12, gridColor=GRID, domainColor=INK, tickColor=INK))


def _dot(df, x, y, tips):
    return alt.Chart(df).mark_point(size=170, color=MODEL, filled=True,
                                    stroke="#FFFFFF", strokeWidth=1.4).encode(
        x=alt.X(f"{x}:Q"), y=alt.Y(f"{y}:Q"), tooltip=tips)


def _maps(r, feed, sweep_v, sweep_f) -> None:
    st.markdown("**Performance maps** — the current point is the amber dot")

    # 1) recovery vs valve resistance (at current frequency)
    rv = pd.DataFrame([{"k": s.valve_resistance, "rec": s.recovery * 100} for s in sweep_v])
    c1 = _style(alt.layer(
        alt.Chart(rv).mark_line(color=LINE, strokeWidth=3, clip=True).encode(
            x=alt.X("k:Q", title="Valve resistance K (bar per (m³/h)²)",
                    scale=_xscale(list(S.K_SWEEP))),
            y=alt.Y("rec:Q", title="Recovery (%)")),
        _dot(pd.DataFrame([{"k": r.valve_resistance, "rec": r.recovery * 100}]), "k", "rec",
             [alt.Tooltip("k:Q", format=".3f", title="K"),
              alt.Tooltip("rec:Q", format=".1f", title="recovery")])),
        "Recovery vs valve resistance")

    # 2) SEC vs recovery (sweeping the valve) — the optimisation curve
    sr = pd.DataFrame([{"rec": s.recovery * 100, "sec": s.sec}
                       for s in sweep_v if s.permeate_flow > 0 and math.isfinite(s.sec)])
    layers2 = [alt.Chart(sr).mark_line(color=LINE, strokeWidth=3, clip=True).encode(
        x=alt.X("rec:Q", title="Recovery (%)"),
        y=alt.Y("sec:Q", title="SEC (kWh/m³)", scale=alt.Scale(zero=False)))]
    if r.permeate_flow > 0 and math.isfinite(r.sec):
        layers2.append(_dot(pd.DataFrame([{"rec": r.recovery * 100, "sec": r.sec}]), "rec", "sec",
                            [alt.Tooltip("rec:Q", format=".1f", title="recovery"),
                             alt.Tooltip("sec:Q", format=".1f", title="SEC")]))
    c2 = _style(alt.layer(*layers2), "Specific energy vs recovery")

    # 3) permeate flow vs frequency (at current valve)
    pf = pd.DataFrame([{"f": s.frequency, "qp": s.permeate_flow} for s in sweep_f])
    c3 = _style(alt.layer(
        alt.Chart(pf).mark_line(color=LINE, strokeWidth=3, clip=True).encode(
            x=alt.X("f:Q", title="VFD frequency (Hz)", scale=_xscale([24, 60])),
            y=alt.Y("qp:Q", title="Permeate flow (m³/h)")),
        _dot(pd.DataFrame([{"f": r.frequency, "qp": r.permeate_flow}]), "f", "qp",
             [alt.Tooltip("f:Q", format=".0f"), alt.Tooltip("qp:Q", format=".2f", title="permeate")])),
        "Production vs frequency (valve untouched)")

    a, b = st.columns(2)
    a.altair_chart(c1, theme=None, width='stretch')
    b.altair_chart(c2, theme=None, width='stretch')
    st.altair_chart(c3, theme=None, width='stretch')
    st.caption("Close the valve (raise K) → recovery rises and SEC falls; raise the frequency "
               "with the valve untouched → more feed, higher pressure (P_b = K·Q²) and more "
               "product. The SEC–recovery curve is the basis for choosing the best operating point.")


def _assumptions():
    with st.expander("Assumptions & limits", expanded=False):
        st.markdown(
            "- **Steady state**, single element; the plant is solved for one operating "
            "pressure that balances the pump, membrane and valve.\n"
            "- **Two controls only** — VFD frequency and the brine valve — matching the plant.\n"
            "- **The valve is described by its measured resistance K** (brine pressure ÷ "
            "brine flow²). The hand-wheel position is not recorded, so no opening %, Cv "
            "curve or cavitation model is assumed.\n"
            f"- **Gauge-to-gauge loss ΔP_gauges = {S.DP_GAUGES:.2f} bar** — measured median "
            "of Exp 1–9, treated as a loss between the feed gauge and the valve; the "
            "membrane's own driving pressure uses ΔPe = 0.2 bar.\n"
            "- Pump and membrane parameters are the block values (manufacturer / "
            "standard-test); **not calibrated** to this unit.\n"
            "- Feed salinity and temperature come from your readings; feed salinity is a grab "
            "sample.\n"
            "- At seawater salinity the valve throttles 30–60 bar across one seat, so "
            "cavitation is expected in normal operation (CF8M body). It is a wear note, not "
            "part of the calculation."
        )


def render(controls: dict, feed: dict) -> None:
    from core import modes as M

    freq_manual = controls.get("frequency", 60.0)
    k_manual = controls.get("valve_resistance", M.K_DEFAULT)
    tds = feed.get("tds", 41000.0)
    temp = feed.get("temperature", 28.0)

    st.subheader("Operating mode")
    mode = st.segmented_control("mode", M.MODE_NAMES, default="Manual",
                                label_visibility="collapsed") or "Manual"
    target_pct = None
    if mode == "Target":
        target_pct = st.number_input("Target recovery (%)", min_value=1.0,
                                     max_value=20.0, value=10.0, step=0.5)
    with st.expander("What the modes do", expanded=False):
        for name in M.MODE_NAMES:
            st.markdown(f"**{name}** — {M.GOALS[name]}")

    note = ""
    if mode == "Manual":
        freq, k = freq_manual, k_manual
    else:
        freq, k, rec, note = M.recommend(mode, tds, temp, target_pct or 10.0)
        msg = (f"**{mode}** → recommended setpoints: VFD **{freq:.0f} Hz**, valve resistance "
               f"**K = {k:.3f}** — turn the hand-wheel until the brine gauge reads "
               f"**{rec.valve_back_pressure:.1f} bar**.  _{M.GOALS[mode]}_  "
               "(The sidebar knobs are overridden in this mode.)")
        if note:
            msg += f"\n\n{note}"
        st.info(msg)

    r = S.simulate(freq, k, tds, temp)

    if r.warnings:
        st.warning("Notes:  " + "  •  ".join(r.warnings))

    st.subheader("Plant KPIs")
    _kpis(r)

    st.divider()
    _streams(r)
    _coupling(r)

    st.divider()
    sweep_v = S.sweep_valve(freq, tds, temp)
    sweep_f = S.sweep_frequency(k, tds, temp)
    _maps(r, feed, sweep_v, sweep_f)

    st.divider()
    _assumptions()
