"""Full system - with Experiments.

Replaces the old Validation page. One flow, top to bottom:

    1. Load the experiment workbook (.xlsx)
    2. Pick an experiment — the count is detected from the sheet
    3. Show that experiment's simulation inputs (Hz, valve %) and feed conditions
    4. Lab vs simulation for every predicted quantity, with the difference and % —
       numbers only, no pass/fail verdict
    5. The equations behind every simulated value, each linked both ways to its row

The full coupled plant (core.system.simulate) is driven ONLY by the two knobs
and the feed conditions taken from the workbook. No lab result is fed into the
model; no parameter is adjusted.
"""
from __future__ import annotations

import math

import streamlit as st

from core import experiments as X
from core import membrane, pump, valve
from core import system as S

ACCENT = "#285A7A"   # app steel blue

# key, label, unit, decimals
ROWS = [
    ("operating_pressure", "Feed (operating) pressure", "bar", 2),
    ("brine_pressure",     "Brine pressure",            "bar", 2),
    ("feed_flow",          "Feed flow",                 "m³/h", 2),
    ("permeate_flow",      "Permeate flow",             "m³/h", 3),
    ("brine_flow",         "Brine flow",                "m³/h", 2),
    ("recovery",           "Recovery",                  "%", 2),
    ("flux",               "Permeate flux",             "LMH", 2),
    ("permeate_tds",       "Permeate TDS",              "mg/L", 1),
    ("brine_tds",          "Brine TDS",                 "mg/L", 0),
    ("rejection",          "Salt rejection",            "%", 2),
    ("power",              "Shaft power",               "kW", 2),
    ("sec",                "Specific energy",           "kWh/m³", 2),
    ("beta",               "Polarisation factor β",     "–", 3),
]
BASIS_TEXT = {"measured": "measured", "derived": "from measurements",
              "workbook calc": "calculated in workbook"}

CSS = f"""
<style>
.fx-step {{ display:flex; align-items:baseline; gap:.6rem; margin:1.6rem 0 .5rem; }}
.fx-step b {{ color:{ACCENT}; font-size:1.05rem; }}
.fx-step span {{ font-size:1.25rem; font-weight:650; }}
.fx-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
.fx-box {{ border:1px solid rgba(128,128,128,.28); border-radius:10px; padding:14px 16px; }}
.fx-box.drive {{ border-left:4px solid {ACCENT}; }}
.fx-box h4 {{ margin:0 0 .15rem; font-size:.95rem; }}
.fx-box p.sub {{ margin:0 0 .7rem; font-size:.82rem; opacity:.7; }}
.fx-kv {{ display:flex; justify-content:space-between; align-items:baseline;
          padding:.3rem 0; border-top:1px dashed rgba(128,128,128,.25); }}
.fx-kv:first-of-type {{ border-top:0; }}
.fx-kv .k {{ font-size:.9rem; opacity:.85; }}
.fx-kv .v {{ font-size:1.35rem; font-weight:650; font-variant-numeric:tabular-nums; }}
.fx-kv .v small {{ font-size:.8rem; font-weight:500; opacity:.7; margin-left:.25rem; }}
.fx-wrap {{ overflow-x:auto; }}
table.fx-cmp {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
table.fx-cmp th {{ text-align:right; font-size:.8rem; font-weight:600; opacity:.75;
                   padding:.5rem .6rem; border-bottom:2px solid rgba(128,128,128,.35); }}
table.fx-cmp th:first-child, table.fx-cmp td:first-child {{ text-align:left; }}
table.fx-cmp td {{ text-align:right; padding:.55rem .6rem;
                   border-bottom:1px solid rgba(128,128,128,.18); white-space:nowrap; }}
table.fx-cmp tr {{ scroll-margin-top:5rem; }}
table.fx-cmp tr:target td {{ background:rgba(40,90,122,.12); }}
table.fx-cmp td .u {{ opacity:.6; font-size:.8rem; margin-left:.2rem; }}
table.fx-cmp td .basis {{ display:block; font-size:.72rem; opacity:.6; }}
table.fx-cmp td.sim {{ font-weight:650; color:{ACCENT}; }}
table.fx-cmp td.pct {{ font-weight:650; }}
a.fx-jump, a.fx-back {{ font-size:.78rem; text-decoration:none; color:{ACCENT};
           border:1px solid {ACCENT}; border-radius:6px; padding:.18rem .5rem; }}
a.fx-jump:hover, a.fx-back:hover {{ background:{ACCENT}; color:#fff; }}
a.fx-jump:focus-visible, a.fx-back:focus-visible {{ outline:2px solid {ACCENT}; outline-offset:2px; }}
.fx-eqhead {{ display:flex; justify-content:space-between; align-items:center; gap:1rem;
              margin-top:1.4rem; padding-top:.9rem; border-top:1px solid rgba(128,128,128,.25);
              scroll-margin-top:5rem; }}
.fx-eqhead span {{ font-weight:650; font-size:1.05rem; }}
.fx-eqhead span em {{ font-style:normal; opacity:.6; font-weight:500; font-size:.85rem; }}
</style>
"""


# ---------------------------------------------------------------------------
# cached work
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _parse(data: bytes):
    return X.load_workbook(data)


@st.cache_data(show_spinner="Solving the coupled plant…")
def _solve(freq: float, opening: float, tds: float, temp: float):
    r = S.simulate(freq, opening, tds, temp)
    # same call system.simulate makes internally at the balanced pressure,
    # kept here so the CH9 working of every membrane value can be shown
    mr = membrane.simulate(r.operating_pressure, tds, temp, r.feed_flow)
    vr = valve.simulate(opening, r.brine_flow)
    return r, mr, vr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _step(n: int, title: str) -> None:
    st.markdown(f'<div class="fx-step"><b>{n}</b><span>{title}</span></div>',
                unsafe_allow_html=True)


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _fmt(x, d: int) -> str:
    return f"{x:,.{d}f}" if _ok(x) else "—"


def _sim_values(r, mr) -> dict:
    return {
        "operating_pressure": r.operating_pressure,
        "brine_pressure": r.operating_pressure - S.ELEMENT_DP,
        "feed_flow": r.feed_flow,
        "permeate_flow": r.permeate_flow,
        "brine_flow": r.brine_flow,
        "recovery": r.recovery * 100.0,
        "flux": r.flux,
        "permeate_tds": r.permeate_tds,
        "brine_tds": r.brine_tds,
        "rejection": r.rejection * 100.0,
        "power": r.power,
        "sec": r.sec,
        "beta": mr.beta,
    }


# ---------------------------------------------------------------------------
# 3 — inputs
# ---------------------------------------------------------------------------
def _inputs(e: X.Experiment) -> None:
    def kv(k, v, u):
        return f'<div class="fx-kv"><span class="k">{k}</span><span class="v">{v}<small>{u}</small></span></div>'

    drive = (
        '<div class="fx-box drive"><h4>Simulation inputs — the two knobs</h4>'
        f'<p class="sub">Taken from {e.label}; these set the operating point.</p>'
        + kv("VFD frequency", _fmt(e.frequency, 1), "Hz")
        + kv("Brine-valve opening", _fmt(e.valve_opening_pct, 2), "% travel")
        + '</div>'
    )
    cond = (
        '<div class="fx-box drive"><h4>Feed conditions</h4>'
        f'<p class="sub">Also from {e.label}; they enter the membrane model.</p>'
        + kv("Feed salinity (TDS)", _fmt(e.feed_tds, 0), "mg/L")
        + kv("Feed temperature", _fmt(e.feed_temperature, 1), "°C")
        + '</div>'
    )
    fixed = (
        '<div class="fx-box"><h4>Held at model defaults</h4>'
        '<p class="sub">Not in the workbook; not adjusted.</p>'
        + kv("Pump health", "1.00", "")
        + kv("Membrane fouling factor", "1.00", "")
        + kv("Element pressure drop ΔPe", f"{S.ELEMENT_DP:g}", "bar")
        + '</div>'
    )
    st.markdown(f'<div class="fx-grid">{drive}{cond}{fixed}</div>', unsafe_allow_html=True)
    st.caption("Everything else on this page — pressure, flows, salinities, energy — "
               "is solved by the model from these inputs alone. No lab result is fed in.")
    if e.notes:
        with st.expander("Conversions applied when reading the workbook"):
            for n in e.notes:
                st.markdown(f"- {n}")


# ---------------------------------------------------------------------------
# 4 — comparison
# ---------------------------------------------------------------------------
def _comparison(sim: dict, lab: dict) -> None:
    body = []
    for key, label, unit, d in ROWS:
        s, lv = sim.get(key), lab.get(key)
        L = lv.value if lv else None
        if _ok(s) and _ok(L):
            diff = s - L
            pct = f"{100.0 * diff / abs(L):+.1f} %" if L != 0 else "—"
            diff_s = f"{diff:+,.{d}f}"
        else:
            pct, diff_s = "—", "—"
        basis = BASIS_TEXT.get(lv.basis, "") if lv else ""
        body.append(
            f'<tr id="cmp-{key}">'
            f'<td>{label}<span class="u">{unit}</span></td>'
            f'<td>{_fmt(L, d)}<span class="basis">{basis}</span></td>'
            f'<td class="sim">{_fmt(s, d)}</td>'
            f'<td>{diff_s}</td>'
            f'<td class="pct">{pct}</td>'
            f'<td><a class="fx-jump" href="#eq-{key}" target="_self">Equation ↓</a></td>'
            '</tr>'
        )
    head = ("<tr><th>Quantity</th><th>Lab</th><th>Simulation</th>"
            "<th>Difference<br>(sim − lab)</th><th>% of lab</th><th></th></tr>")
    st.markdown(f'<div class="fx-wrap"><table class="fx-cmp">{head}{"".join(body)}</table></div>',
                unsafe_allow_html=True)
    st.caption("% of lab = 100 · (simulation − lab) / |lab|. A positive value means the "
               "simulation is above the lab figure. Under each lab value: whether it was "
               "measured directly, formed from this experiment's measurements, or "
               "calculated inside the workbook.")


# ---------------------------------------------------------------------------
# 5 — equations
# ---------------------------------------------------------------------------
def _equations(r, mr, vr) -> dict:
    sw, s5, s6 = r.worked, mr.step_worked.get("step5", {}), mr.step_worked.get("step6", {})
    P, dpe = r.operating_pressure, S.ELEMENT_DP
    cf = pump.v("calc_factor")
    power_tex = (rf"P_{{shaft}} = \frac{{16.7\,Q_f\,P}}{{{cf:g}}} = "
                 rf"\frac{{16.7\times {r.feed_flow:.2f}\times {P:.2f}}}{{{cf:g}}}"
                 rf" = {r.power:.2f}\ \mathrm{{kW}}")
    pb_tex = (rf"P_b = P - \Delta P_e = {P:.2f} - {dpe:g} = {P - dpe:.2f}\ \mathrm{{bar}}")

    def pick(d, *keys):
        return [d[k] for k in keys if k in d]

    return {
        "operating_pressure": (
            "Solved, not set. The pump fixes the feed flow; the membrane splits it at "
            "pressure P; the valve must pass the brine. P is found by bisection where the "
            "valve back-pressure equals the brine-side pressure P − ΔPe.",
            pick(sw, "pressure") + pick(vr.worked, "cv", "dp")),
        "brine_pressure": (
            "Brine-side pressure = operating pressure less the element drop; at the solved "
            "point it equals the valve back-pressure.",
            [pb_tex] + pick(vr.worked, "dp")),
        "feed_flow": (
            "Positive-displacement pump: flow follows shaft speed only (rpm = 30 · Hz), "
            "independent of pressure.",
            pick(sw, "qfeed")),
        "permeate_flow": (
            "CH9 Step 5 at the solved pressure: water permeability at T, net driving "
            "pressure, flux, then permeate flow.",
            pick(s5, "kwT", "ndp", "flux", "qp")),
        "brine_flow": (
            "Mass balance on the element.",
            pick(sw, "balance") + pick(s5, "qc")),
        "recovery": ("Permeate over feed.", pick(sw, "recovery")),
        "flux": ("CH9 Step 5 — solution-diffusion water flux.", pick(s5, "kwT", "ndp", "flux")),
        "permeate_tds": (
            "CH9 Step 6, flux-effect form (the one the model uses): salt passage Ks(T) "
            "diluted by the water flux J.",
            pick(s6, "ksT", "cp_flux")),
        "brine_tds": ("CH9 Step 5 — concentration build-up at the solved recovery.",
                      pick(s5, "cc")),
        "rejection": ("CH9 Step 6.", pick(s6, "cp_flux", "rej")),
        "power": ("Danfoss absorbed-power equation at the solved pressure "
                  "(calc-factor includes pump efficiency).", [power_tex]),
        "sec": ("Shaft power per m³ of permeate.", pick(sw, "sec")),
        "beta": ("CH9 Step 5 — concentration-polarisation factor.", pick(s5, "qc", "beta")),
    }


def _equation_section(eqs: dict, lab: dict) -> None:
    for key, label, unit, _ in ROWS:
        intro, lines = eqs.get(key, ("", []))
        st.markdown(
            f'<div class="fx-eqhead" id="eq-{key}"><span>{label} <em>{unit}</em></span>'
            f'<a class="fx-back" href="#cmp-{key}" target="_self">↑ Back to comparison</a></div>',
            unsafe_allow_html=True)
        if intro:
            st.caption(intro)
        for tex in lines:
            st.latex(tex)
        lv = lab.get(key)
        if lv and lv.how:
            st.caption("Lab side, formed from this experiment's readings:")
            st.latex(lv.how)


def _full_steps(mr) -> None:
    titles = {"step1": "Step 1 — preliminary concentrations",
              "step2": "Step 2 — design flux → permeate flow",
              "step3": "Step 3 — permeabilities Kw, Ks at 25 °C",
              "step4": "Step 4 — preliminary feed pressure",
              "step5": "Step 5 — flows, recovery, β (iterated)",
              "step6": "Step 6 — permeate quality",
              "step7": "Step 7 — cross-flow velocity"}
    with st.expander("Full membrane working — CH9 Steps 1–7 at the solved pressure"):
        st.caption("Steps 1, 2 and 4 are design relations shown at the solved point; "
                   "Steps 5–7 are what the model solves.")
        for k, t in titles.items():
            lines = mr.step_worked.get(k) or {}
            if lines:
                st.markdown(f"**{t}**")
                for body in lines.values():
                    st.latex(body)


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
def render(controls: dict | None = None, feed: dict | None = None) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.header("Full system — with experiments")
    st.caption("Drive the full coupled plant with the settings and feed conditions of one "
               "lab experiment, then set the simulated results beside what the plant measured.")

    # 1 — workbook
    _step(1, "Load the experiment workbook")
    up = st.file_uploader("Experiment workbook (.xlsx)", type=["xlsx", "xlsm"],
                          label_visibility="collapsed")
    if up is None:
        st.info("Upload the workbook with the “Readings” sheet — one column per "
                "experiment (Exp 1, Exp 2, …). The number of experiments is read from it.")
        return
    try:
        wb = _parse(up.getvalue())
    except X.WorkbookError as err:
        st.error(f"The workbook could not be read: {err}")
        return
    except Exception as err:  # corrupt file, not an xlsx, …
        st.error(f"The file could not be opened as a workbook ({type(err).__name__}: {err}).")
        return

    # 2 — experiment
    _step(2, "Choose the experiment")
    st.caption(f"{wb.count} experiments found on sheet “{wb.sheet}”.")
    labels = [e.label for e in wb.experiments]
    pills = getattr(st, "pills", None)
    if pills:
        choice = pills("Experiment", labels, selection_mode="single", default=labels[0],
                       label_visibility="collapsed") or labels[0]
    else:
        choice = st.selectbox("Experiment", labels, label_visibility="collapsed")
    e = wb.experiments[labels.index(choice)]

    # 3 — inputs
    _step(3, f"Simulation inputs for {e.label}")
    _inputs(e)
    if not all(_ok(x) for x in (e.frequency, e.valve_opening_pct, e.feed_tds, e.feed_temperature)):
        st.error(f"{e.label} is missing an input (frequency, valve opening, feed TDS or "
                 "temperature), so it cannot be simulated.")
        return

    r, mr, vr = _solve(e.frequency, e.valve_opening_pct, e.feed_tds, e.feed_temperature)
    if not r.converged:
        st.info("The solver found no pressure balance inside 0.1–82.7 bar for these "
                "inputs; the values below are at the nearest bound.")
    if r.warnings:
        with st.expander("Model notes at this operating point"):
            for w in r.warnings:
                st.markdown(f"- {w}")

    sim = _sim_values(r, mr)
    lab = X.lab_results(e, area=membrane.p("area"))

    # 4 — comparison
    _step(4, "Lab vs simulation")
    _comparison(sim, lab)

    # 5 — equations
    _step(5, "How each simulated value was calculated")
    st.caption(f"Every line is the model's own equation with {e.label}'s numbers substituted.")
    _equation_section(_equations(r, mr, vr), lab)
    st.markdown("")
    _full_steps(mr)
