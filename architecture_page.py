"""Architecture overview page.

A clean, native rendering of the system architecture — boxed layers in the
app's own identity, each with a one-line explanation. No ASCII art, no phase
tags. Reachable from the "Architecture" mode in the sidebar.
"""
from __future__ import annotations

import streamlit as st

MUTED = "#8A8578"


def _arrow() -> None:
    st.markdown(
        f"<div style='text-align:center;color:{MUTED};font-size:1.15rem;"
        f"margin:-0.2rem 0 0.1rem'>↓</div>",
        unsafe_allow_html=True,
    )


def _box(title: str, desc: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(desc)


def _cell(col, title: str, desc: str) -> None:
    with col.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(desc)


def render() -> None:
    st.title("System architecture")
    st.caption("How the whole digital twin fits together — the real plant, the "
               "data that feeds the model, the model itself, and the people who "
               "use it.")
    st.write("")

    # --- Physical plant ------------------------------------------------
    _box("Physical plant",
         "The real SWRO skid: pump, membrane, brine valve and gauges. This is "
         "what the twin mirrors and, eventually, advises.")

    c1, c2 = st.columns(2)
    c1.markdown(f"<div style='text-align:center;color:{MUTED}'>measures ↓</div>",
                unsafe_allow_html=True)
    c2.markdown(f"<div style='text-align:center;color:{MUTED}'>↑ advises</div>",
                unsafe_allow_html=True)

    # --- Data & Advisory (side by side) --------------------------------
    d, a = st.columns(2)
    _cell(d, "Data layer",
          "What feeds the model: manufacturer specifications, hand-read gauge "
          "values, and the records from each plant test run. Feed salinity is "
          "only known from a grab sample, so it is treated with lower confidence.")
    _cell(a, "Advisory layer",
          "What the twin suggests back: a recommended VFD frequency and valve "
          "opening. A human always reviews and executes — nothing is actuated "
          "automatically.")

    _arrow()

    # --- Model (the twin) ---------------------------------------------
    with st.container(border=True):
        st.markdown("**Model — the digital twin**")
        st.caption("The virtual copy of the plant: it predicts behaviour, "
                   "compares against measurements, and finds the best settings.")

        m1, m2, m3, m4 = st.columns(4)
        _cell(m1, "Model core",
              "The pump, membrane and valve equations, each from manufacturer data.")
        _cell(m2, "Solver",
              "Couples the three blocks through one balancing pressure to find "
              "the operating point.")
        _cell(m3, "Analysis",
              "Turns the solution into KPIs, performance curves and the best "
              "operating window.")
        _cell(m4, "Calibration",
              "Tunes the unknown parameters (A, B, Cv, efficiency) so the model "
              "matches this specific plant.")

        v1, v2 = st.columns(2)
        _cell(v1, "Validation & uncertainty",
              "An error band and a threshold, so a real change is told apart "
              "from measurement noise.")
        _cell(v2, "Assumptions & limits",
              "Steady-state, single element, and the range where the model is valid.")

        _box("Diagnosis",
             "Compares model with measurement; a gap past the threshold flags "
             "wear or fouling.")

    _arrow()

    # --- Interface -----------------------------------------------------
    _box("Interface",
         "The web app you are using: mode selector, controls, plant schematic, "
         "KPIs, charts and sources.")

    _arrow()

    # --- People --------------------------------------------------------
    _box("People",
         "Operator runs it, examiner verifies it, developer builds it.")

    st.divider()

    # --- Platform / delivery (foundation) ------------------------------
    _box("Platform / delivery",
         "Code and configuration live in a single GitHub repository; Streamlit "
         "Cloud hosts it and serves it as a web link.")

    st.caption("Loop:  plant → data → model → interface → people → advisory → "
               "(human) → plant.")
