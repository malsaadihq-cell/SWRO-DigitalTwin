"""Simulation & Experiments Comparison.

Replaces the old Validation page. One flow, top to bottom:

    1. Load the experiment workbook (.xlsx)
    2. Pick an experiment — the count is detected from the sheet
    3. Show that experiment's simulation inputs (Hz, valve %) and feed conditions
    4. Lab vs simulation for every predicted quantity, with the difference and % —
       numbers only, no pass/fail verdict
    5. The equations behind every simulated value, each linked both ways to its row

The full coupled plant (core.system.simulate) is driven by the two knobs and
the feed conditions taken from the workbook. The valve knob is the run's
measured resistance K = P_brine / Q_brine² (the hand-wheel position is never
recorded), so the brine pressure is an input in disguise and its comparison
row is labelled as such. No parameter is adjusted.
"""
from __future__ import annotations

import math

import streamlit as st

from core import experiments as X
from core import membrane, pump, valve
from core import system as S

ACCENT = "#285A7A"   # app steel blue

# The "Fixed model values" card: the values that are the same for every run,
# each with its source. Set to False to hide it.
SHOW_MODEL_DEFAULTS = True

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
              "workbook calc": "calculated in workbook",
              "workbook": "from workbook",
              "sets K": "measured · used to set K"}

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
def _solve(freq: float, k: float, tds: float, temp: float, age: float):
    r = S.simulate(freq, k, tds, temp, membrane_age=age)
    # the membrane result at the solved point (element inlet pressure, plant
    # salt passage) comes with the system result, so its CH9 working can be shown
    vr = valve.simulate(k, r.brine_flow)
    return r, r.membrane, vr


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
        "brine_pressure": r.valve_back_pressure,
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
def _inputs(e: X.Experiment, age: float, age_from_sheet: bool) -> None:
    def kv(k, v, u):
        return f'<div class="fx-kv"><span class="k">{k}</span><span class="v">{v}<small>{u}</small></span></div>'

    drive = (
        '<div class="fx-box drive"><h4>Simulation inputs — the two knobs</h4>'
        f'<p class="sub">Taken from {e.label}; these set the operating point.</p>'
        + kv("VFD frequency", _fmt(e.frequency, 1), "Hz")
        + kv("Valve resistance K", _fmt(e.valve_resistance, 3), "bar/(m³/h)²")
        + f'<p class="sub" style="margin:.4rem 0 0">K = brine pressure ÷ brine flow² = '
          f'{_fmt(e.raw.get("brine_pressure"), 2)} ÷ {_fmt(e.raw.get("brine_flow"), 2)}² — '
          'the hand-wheel position is not recorded, so the valve enters by its effect.</p>'
        + '</div>'
    )
    cond = (
        '<div class="fx-box drive"><h4>Feed conditions</h4>'
        f'<p class="sub">Also from {e.label}; they enter the membrane model.</p>'
        + kv("Feed salinity (TDS)", _fmt(e.feed_tds, 0), "mg/L")
        + kv("Feed temperature", _fmt(e.feed_temperature, 1), "°C")
        + kv("Membrane age", f"{age:g}", "years")
        + ('<p class="sub" style="margin:0">Membrane age from the workbook.</p>'
           if age_from_sheet else
           '<p class="sub" style="margin:0">Membrane age not in the workbook — value entered '
           'above (from the plant records).</p>')
        + '</div>'
    )
    mp = membrane.PARAMS
    fixed = (
        '<div class="fx-box"><h4>Fixed model values</h4>'
        '<p class="sub">Same for every run; not adjusted to the results.</p>'
        + kv("Feed − brine gauge ΔP", f"{S.DP_GAUGES:.2f}", "bar")
        + '<p class="sub" style="margin:0 0 .3rem">Measured: median of the first campaign '
          '(Exp 1–9)</p>'
        + kv("Min. salt rejection, new element", f"{mp['SR_min'].value*100:.1f}", "%")
        + '<p class="sub" style="margin:0 0 .3rem">SWC4 MAX spec sheet; CH9 p. 247, 259</p>'
        + kv("Salt-passage increase", f"{mp['sp_increase'].value*100:.0f}", "% / year")
        + '<p class="sub" style="margin:0 0 .3rem">CH9 Table 4 p. 248 — Hydranautics, '
          'surface intake</p>'
        + '</div>'
    )
    cards = drive + cond + (fixed if SHOW_MODEL_DEFAULTS else "")
    st.markdown(f'<div class="fx-grid">{cards}</div>', unsafe_allow_html=True)
    st.caption("Pressure, flows, salinities and energy are solved by the model from these "
               "inputs. Because K is formed from the measured brine pressure, the simulated "
               "brine pressure follows it closely by construction — that row is not a test.")
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
               "measured directly, formed from this experiment's measurements, calculated "
               "inside the workbook, or used to set the valve resistance K (so not a test).")


# ---------------------------------------------------------------------------
# 5 — equations
# ---------------------------------------------------------------------------
def _equations(r, mr, vr, age: float) -> dict:
    sw, s5, s6 = r.worked, mr.step_worked.get("step5", {}), mr.step_worked.get("step6", {})
    P = r.operating_pressure
    cf = pump.v("calc_factor")
    power_tex = (rf"P_{{shaft}} = \frac{{16.7\,Q_f\,P}}{{{cf:g}}} = "
                 rf"\frac{{16.7\times {r.feed_flow:.2f}\times {P:.2f}}}{{{cf:g}}}"
                 rf" = {r.power:.2f}\ \mathrm{{kW}}")
    dpg = S.DP_GAUGES

    def pick(d, *keys):
        return [d[k] for k in keys if k in d]

    return {
        "operating_pressure": (
            "Solved, not set. The pump delivers its flow at this pressure; the membrane splits it at "
            f"pressure P; the valve must pass the brine. P is found by bisection where the "
            f"valve back-pressure K·Qb² equals the brine-gauge pressure P − ΔP_gauges "
            f"(ΔP_gauges = {dpg:.2f} bar, measured median).",
            pick(sw, "pressure", "brine_p", "p_mem")),
        "brine_pressure": (
            "Valve back-pressure at the solved brine flow. K came from this run's measured "
            "brine pressure, so this value tracks the lab figure by construction.",
            pick(vr.worked, "dp") + pick(sw, "brine_p")),
        "feed_flow": (
            "Positive-displacement pump (Danfoss data): geometric flow at the slipped shaft "
            "speed, less the internal leakage that grows with the outlet pressure.",
            pick(sw, "rpm", "leak", "qfeed")),
        "permeate_flow": (
            "CH9 Step 5 at the element inlet pressure: water permeability at T, net driving "
            "pressure, flux, then permeate flow.",
            pick(sw, "p_mem") + pick(s5, "kwT", "ndp", "flux", "qp")),
        "brine_flow": (
            "Mass balance on the element.",
            pick(sw, "balance") + pick(s5, "qc")),
        "recovery": ("Permeate over feed.", pick(sw, "recovery")),
        "flux": ("CH9 Step 5 — solution-diffusion water flux.", pick(s5, "kwT", "ndp", "flux")),
        "permeate_tds": (
            f"CH9 Step 6, flux-effect form: salt permeability Ks(T) of the installed element "
            f"({age:g} years: ESS minimum rejection 99.7 %, aged 7 %/yr — CH9 Table 4 p. 248) "
            f"diluted by the flux J. Water permeability Kw is not aged: cleaning restores it, "
            f"while the salt-passage increase is not recovered.",
            [membrane.plant_salt_passage(age)["worked"][k] for k in ("ksmin", "ksplant", "factor")]
            + pick(s6, "ksT", "cp_flux")),
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


# NDP below which the runs so far show large permeate errors (+54 %, +73 %); an
# observation from the data, used only to warn — never fed into the model.
LOW_NDP_BAR = 10.0


def _validity(e: X.Experiment, r, mr, lab) -> None:
    """Flags that say, for THIS run, whether the comparison below can be trusted."""
    p_star = mr.delta_pi + S.DP_GAUGES / 2.0          # feed pressure where NDP = 0
    if mr.ndp <= 0 or r.permeate_flow <= 0:
        st.error(
            f"**Outside the model's range — no permeate predicted.** The solved feed pressure "
            f"({r.operating_pressure:.1f} bar) is below the ≈ {p_star:.1f} bar needed to "
            f"overcome the osmotic pressure (net driving pressure {mr.ndp:.1f} bar). This "
            f"happens when the valve resistance is low (K = {e.valve_resistance:.3f}): the "
            f"valve builds too little back-pressure. The real element still gave "
            f"{lab['permeate_flow'].value or 0:.3f} m³/h, so permeate flow, flux, recovery, "
            f"permeate TDS and rejection rows (−100 %) are not a meaningful comparison here.")
    elif mr.ndp < LOW_NDP_BAR:
        st.warning(
            f"**Low driving pressure ({mr.ndp:.1f} bar).** The feed pressure is only "
            f"{r.operating_pressure - p_star:.1f} bar above the ≈ {p_star:.1f} bar osmotic "
            f"threshold, so a small error in pressure or salinity makes a large relative "
            f"error in permeate flow and quality. In the runs so far, every run below about "
            f"{LOW_NDP_BAR:.0f} bar showed permeate errors of +50 % or more.")
    q_lab = lab["feed_flow"].value
    q_geo = pump.theoretical_flow(pump.rpm_from_frequency(e.frequency))
    if q_lab and q_lab > q_geo:
        st.warning(
            f"**Lab flows exceed the pump's capacity.** Permeate + brine = {q_lab:.2f} m³/h, "
            f"but the pump's geometric flow at {e.frequency:.0f} Hz is {q_geo:.2f} m³/h "
            f"(137 cm³/rev × {pump.rpm_from_frequency(e.frequency):.0f} rpm), and a "
            f"positive-displacement pump cannot deliver more. A flow reading is likely off, "
            f"so the flow-based rows of this run are suspect.")


def _limitations() -> None:
    st.markdown(
        "- **Low valve resistance → no prediction.** When K is small the valve builds little "
        "back-pressure, the feed pressure falls toward the osmotic pressure "
        "(≈ 32 bar at ≈ 37,000 mg/L), and the model predicts no permeate while the real "
        "element still makes a little. For the plant's typical feed (≈ 37,250 mg/L, 29 °C) "
        "this happens below K ≈ 0.135 at 60 Hz and K ≈ 0.16 at 55 Hz (Exp 2 of the first "
        "campaign: K = 0.106). Saltier or colder feed raises the threshold.\n"
        "- **Near that threshold the errors are large** — Exp 3 and Exp 8 (net driving "
        "pressure 5–8 bar) over-predict permeate by 50–75 %. The model is reliable only "
        "well above the osmotic pressure.\n"
        "- **K is taken from the same run.** The valve enters by its measured resistance, "
        "so the brine-pressure row is not an independent test, and the feed-pressure "
        "prediction leans on it. A true test of the valve law needs K from one run used to "
        "predict another at a different frequency with the hand-wheel untouched.\n"
        "- **Pump above its rated speed.** The plant runs at ≈ 1630–1780 rpm; the Danfoss "
        "data stop at 1500 rpm, so the pump flow is an extrapolation, and the leakage term "
        "is an assumption fixed by one rated point.\n"
        "- **Fixed gauge loss.** ΔP = 4.48 bar is the median of the first campaign; the "
        "measured value varies from run to run (3.5–8.6 bar), which shifts the predicted "
        "pressure.\n"
        "- **Membrane condition is assumed, not measured.** Salt permeability is aged "
        "7 %/yr for the entered age (CH9 Table 4); the age is not yet confirmed, and the "
        "permeate TDS is very sensitive to it. Water permeability is kept at catalogue.\n"
        "- **Salinity from conductivity.** TDS = EC × k with fixed k (0.66 feed and brine, "
        "0.50 permeate); errors in k pass straight into the osmotic pressure and the "
        "permeate TDS.\n"
        "- **Simplified membrane physics** (CH9): one lumped element, osmotic pressure by "
        "the 0.8 bar / 1000 mg/L rule, polarisation reported but not added to the osmotic "
        "pressure, steady state only.\n"
        "- **Lab-side derived values.** Feed flow, recovery and flux on the lab side are "
        "formed from the permeate and brine flow meters, so a flow-meter error appears in "
        "all of them."
    )


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
    st.header("Simulation & experiments comparison")
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
    age_from_sheet = e.membrane_age is not None
    if age_from_sheet:
        age = e.membrane_age
    else:
        age = st.number_input(
            "Membrane age (years) — not in the workbook; enter it from the plant records",
            min_value=0.0, max_value=20.0, value=float(membrane.p("age")), step=0.5)
    _inputs(e, age, age_from_sheet)
    if not all(_ok(x) for x in (e.frequency, e.valve_resistance, e.feed_tds, e.feed_temperature)):
        st.error(f"{e.label} is missing an input (frequency, brine pressure / flow, feed TDS "
                 "or temperature), so it cannot be simulated.")
        return

    r, mr, vr = _solve(e.frequency, e.valve_resistance, e.feed_tds, e.feed_temperature, age)
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
    _validity(e, r, mr, lab)
    _comparison(sim, lab)

    # 5 — equations
    _step(5, "How each simulated value was calculated")
    st.caption(f"Every line is the model's own equation with {e.label}'s numbers substituted.")
    _equation_section(_equations(r, mr, vr, age), lab)
    st.markdown("")
    _full_steps(mr)

    # 6 — limits
    _step(6, "Limits of the simulation")
    _limitations()
