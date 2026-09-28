"""Pump-only view.

Built to answer three questions the examiner asks every time:
    "where did these numbers come from?"  -> a Characteristics table with a
                                             plain-language meaning and the
                                             exact Danfoss manual page
    "where are the laws?"                 -> the equations, shown as maths
    "how did you get THIS number?"        -> each law re-printed with the
                                             current values substituted in
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import pump

TEAL = "#0F766E"
RED = "#B91C1C"


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
                {"Parameter": k.replace("_", " "),
                 "What it is": s.what,
                 "Value": f"{s.value:g}",
                 "Unit": s.unit,
                 "Source": s.source}
                for k, s in pump.CHARACTERISTICS.items()
            ]
            df = pd.DataFrame(rows)
            st.dataframe(
                df, hide_index=True, width='stretch',
                column_config={
                    "What it is": st.column_config.TextColumn(width="medium"),
                    "Source": st.column_config.TextColumn(width="large"),
                },
            )


def _curve_flow_vs_rpm(r: pump.PumpResult) -> alt.LayerChart:
    ref = pd.DataFrame(pump.flow_reference(), columns=["rpm", "flow"])
    line = alt.Chart(ref).mark_line(color=TEAL, strokeWidth=2).encode(
        x=alt.X("rpm:Q", title="Speed (rpm)"),
        y=alt.Y("flow:Q", title="Flow (m³/h)"),
    )
    point = pd.DataFrame([{"rpm": r.rpm, "flow": r.flow}])
    dot = alt.Chart(point).mark_point(size=160, color=RED, filled=True).encode(
        x="rpm:Q", y="flow:Q",
        tooltip=[alt.Tooltip("rpm:Q", format=".0f"),
                 alt.Tooltip("flow:Q", format=".2f", title="flow (m³/h)")],
    )
    return (line + dot).properties(
        title="Flow vs speed — Danfoss manual p. 25 (line) with operating point",
        height=300)


def _curve_power_vs_pressure(r: pump.PumpResult) -> alt.LayerChart:
    ref = pd.DataFrame(pump.power_reference(r.flow), columns=["pressure", "power"])
    line = alt.Chart(ref).mark_line(color=TEAL, strokeWidth=2).encode(
        x=alt.X("pressure:Q", title="Outlet pressure (bar)"),
        y=alt.Y("power:Q", title="Shaft power (kW)"),
    )
    point = pd.DataFrame([{"pressure": r.outlet_pressure, "power": r.shaft_power}])
    dot = alt.Chart(point).mark_point(size=160, color=RED, filled=True).encode(
        x="pressure:Q", y="power:Q",
        tooltip=[alt.Tooltip("pressure:Q", format=".1f", title="p_out (bar)"),
                 alt.Tooltip("power:Q", format=".2f", title="power (kW)")],
    )
    return (line + dot).properties(
        title="Power vs pressure — Danfoss manual p. 26 (line) at current flow",
        height=300)


def render(controls: dict, feed: dict) -> None:
    r = pump.simulate(
        frequency_hz=controls.get("frequency", 40.0),
        outlet_pressure=controls.get("outlet_pressure", 55.0),
        health_factor=controls.get("health_factor", 100.0) / 100.0,
        inlet_pressure=feed.get("suction", 3.0),
    )

    if r.warnings:
        st.warning("Outside the manufacturer envelope:  "
                   + "  •  ".join(r.warnings))

    st.subheader("Key performance indicators")
    _kpi_row(r)

    st.subheader("Where these numbers come from")
    _equations_and_sources(r)

    st.subheader("Performance maps — model vs manufacturer reference")
    st.caption("Teal line = Danfoss reference. Red dot = current operating "
               "point. On the plant, overlay measured points here; a gap from "
               "the line flags wear or lost efficiency.")
    left, right = st.columns(2)
    left.altair_chart(_curve_flow_vs_rpm(r), width='stretch')
    right.altair_chart(_curve_power_vs_pressure(r), width='stretch')
