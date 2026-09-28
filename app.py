"""Digital twin of the Rabigh pilot SWRO plant — interface foundation.

This is the SHELL only: the controls, the KPI slots, the chart slots, and
one clearly-marked seam where the model will plug in. There is no physics
here yet. Every result reads "—" until the pump / membrane / valve models
are connected, one block at a time.

Run:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------
# What each simulation mode exposes.
#
# This one dict is the backbone of the page: it says, per mode, which
# controls are live, which KPIs are shown, and which charts are drawn.
# Adding or changing a mode is a data edit here, not new UI code.
# ---------------------------------------------------------------------
CONTROLS = {
    "frequency":      dict(label="VFD frequency", unit="Hz",  min=24.0, max=50.0,  default=40.0, step=0.5),
    "outlet_pressure": dict(label="Pump outlet pressure", unit="bar", min=30.0, max=70.0, default=55.0, step=0.5),
    "health_factor":  dict(label="Pump health (simulate wear)", unit="%", min=80.0, max=100.0, default=100.0, step=1.0),
    "valve_opening":  dict(label="Brine valve opening", unit="%", min=0.0, max=100.0, default=60.0, step=1.0),
    "feed_pressure":  dict(label="Feed pressure", unit="bar", min=30.0, max=70.0,  default=55.0, step=0.5),
    "valve_dp":       dict(label="Pressure drop across valve", unit="bar", min=1.0, max=70.0, default=50.0, step=1.0),
}

KPIS = {
    "recovery":      dict(label="Recovery", unit="%"),
    "flux":          dict(label="Permeate flux", unit="LMH"),
    "rejection":     dict(label="Salt rejection", unit="%"),
    "sec":           dict(label="Specific energy", unit="kWh/m³"),
    "feed_flow":     dict(label="Feed flow", unit="m³/h"),
    "permeate_flow": dict(label="Permeate flow", unit="m³/h"),
    "brine_flow":    dict(label="Brine flow", unit="m³/h"),
    "shaft_power":   dict(label="Shaft power", unit="kW"),
    "valve_flow":    dict(label="Brine flow", unit="m³/h"),
}

# (title, x-axis label, y-axis label)
CHARTS = {
    "flux_vs_p":       ("Permeate flux vs feed pressure", "Feed pressure (bar)", "Flux (LMH)"),
    "sec_vs_rec":      ("Specific energy vs recovery",    "Recovery (%)",        "SEC (kWh/m³)"),
    "rej_vs_p":        ("Salt rejection vs feed pressure", "Feed pressure (bar)", "Salt rejection (%)"),
    "flow_vs_freq":    ("Feed flow vs VFD frequency",     "Frequency (Hz)",      "Feed flow (m³/h)"),
    "power_vs_p":      ("Shaft power vs feed pressure",   "Feed pressure (bar)", "Shaft power (kW)"),
    "brine_vs_open":   ("Brine flow vs valve opening",    "Valve opening (%)",   "Brine flow (m³/h)"),
}

MODES = {
    "Full system": dict(
        controls=["frequency", "valve_opening"],
        kpis=["recovery", "flux", "rejection", "sec"],
        charts=["flux_vs_p", "sec_vs_rec", "rej_vs_p"],
        note="Both knobs are live. The model solves the operating point and every KPI.",
    ),
    "Pump only": dict(
        controls=["frequency", "outlet_pressure", "health_factor"],
        kpis=["feed_flow", "shaft_power"],
        charts=["flow_vs_freq", "power_vs_p"],
        note="Danfoss APP 11/1500. Frequency sets flow; outlet pressure is a "
             "free input here (in the full system it is solved). Health < 100% "
             "simulates a worn pump.",
    ),
    "Membrane only": dict(
        controls=["feed_pressure"],
        kpis=["permeate_flow", "flux", "rejection"],
        charts=["flux_vs_p", "rej_vs_p"],
        note="Drive the element with a feed pressure directly; the pump is out of the loop here.",
    ),
    "Valve only": dict(
        controls=["valve_opening", "valve_dp"],
        kpis=["valve_flow"],
        charts=["brine_vs_open"],
        note="Characterise the throttling valve on its own: flow passed vs opening and pressure drop.",
    ),
}

PLACEHOLDER = "—"


# ---------------------------------------------------------------------
# The model seam. Empty on purpose.
# ---------------------------------------------------------------------
def run_model(mode: str, controls: dict, feed: dict):
    """Where the pump / membrane / valve models will connect.

    Returns None for now, which tells the whole page to render its empty
    state. When we build a block, this returns a result object and the
    KPIs and charts fill themselves in — no other UI code changes.
    """
    return None


# ---------------------------------------------------------------------
# UI pieces
# ---------------------------------------------------------------------
def _slider(key: str) -> float:
    c = CONTROLS[key]
    return st.sidebar.slider(
        f"{c['label']} ({c['unit']})",
        min_value=c["min"], max_value=c["max"],
        value=c["default"], step=c["step"],
    )


# controls that set the operating point vs. controls that inject a fault
OPERATING_CONTROLS = ["frequency", "outlet_pressure", "feed_pressure",
                      "valve_opening", "valve_dp"]
WHATIF_CONTROLS = ["health_factor"]


def sidebar() -> tuple[str, dict, dict]:
    st.sidebar.header("Controls")
    mode = st.sidebar.segmented_control(
        "Simulation mode",
        options=list(MODES.keys()),
        default="Full system",
    ) or "Full system"
    st.sidebar.caption(MODES[mode]["note"])

    keys = MODES[mode]["controls"]
    controls: dict = {}

    op_keys = [k for k in keys if k in OPERATING_CONTROLS]
    wi_keys = [k for k in keys if k in WHATIF_CONTROLS]

    if op_keys:
        st.sidebar.divider()
        st.sidebar.markdown("**Operating point**")
        for key in op_keys:
            controls[key] = _slider(key)
            if key == "frequency":
                st.sidebar.caption(f"≈ {controls[key] * 30:.0f} rpm")

    if wi_keys:
        st.sidebar.divider()
        st.sidebar.markdown("**Condition — what-if**")
        for key in wi_keys:
            controls[key] = _slider(key)
        st.sidebar.caption("100% is a healthy pump; lower it to simulate wear "
                           "and watch the operating point drop off the curve.")

    st.sidebar.divider()
    with st.sidebar.expander("Feed conditions", expanded=False):
        feed = dict(
            tds=st.number_input("Feed TDS (mg/L)", value=41000, step=500),
            temperature=st.number_input("Feed temperature (°C)", value=28.0, step=0.5),
            suction=st.number_input("Suction pressure (bar)", value=3.0, step=0.1),
        )
        st.caption("Replace these with your on-site readings.")

    return mode, controls, feed


def kpi_row(mode: str, result) -> None:
    keys = MODES[mode]["kpis"]
    cols = st.columns(len(keys))
    for col, key in zip(cols, keys):
        spec = KPIS[key]
        value = PLACEHOLDER
        if result is not None:
            value = result.get(key, PLACEHOLDER)
        col.metric(f"{spec['label']} ({spec['unit']})", value)


def chart_slot(chart_key: str, result) -> None:
    title, xlab, ylab = CHARTS[chart_key]
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if result is None:
            st.caption(f"{ylab}  vs  {xlab}")
            st.markdown(
                "<div style='height:150px;display:flex;align-items:center;"
                "justify-content:center;color:#7b8a8f;'>"
                "No data yet — connect the model to populate this chart."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            # When a model is connected it hands back plottable data and
            # this branch draws it. Left empty until then.
            st.line_chart(result["charts"][chart_key])


def charts_section(mode: str, result) -> None:
    chart_keys = MODES[mode]["charts"]
    cols = st.columns(len(chart_keys))
    for col, ckey in zip(cols, chart_keys):
        with col:
            chart_slot(ckey, result)


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="SWRO Digital Twin — Rabigh Pilot",
        page_icon="💧",
        layout="wide",
    )

    st.title("SWRO Digital Twin — Rabigh Pilot Plant")
    st.caption("Phase 1 · steady-state model of the pilot single-element "
               "seawater RO skid, built block by block from plant and "
               "manufacturer data.")

    mode, controls, feed = sidebar()

    # Whole-plant schematic, with the current block highlighted.
    import schematic
    st.markdown(
        f'<div style="max-width:720px;margin:0.25rem auto 0.5rem;">'
        f'{schematic.system_svg(schematic.MODE_TO_BLOCK.get(mode, "all"))}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Built blocks get their own rich, fully-sourced page.
    if mode == "Pump only":
        import pump_page
        pump_page.render(controls, feed)
        return

    # Unbuilt blocks still show the interface foundation (empty state).
    st.info(
        "Interface foundation. The controls on the left are live; the KPIs "
        "and charts fill in once this block's model is connected. Pump is "
        "done — try the “Pump only” mode."
    )
    st.subheader("Key performance indicators")
    kpi_row(mode, None)

    st.subheader("Performance maps")
    charts_section(mode, None)


if __name__ == "__main__":
    main()
