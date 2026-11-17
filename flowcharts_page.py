"""Flowcharts — the logic of each working block, drawn as flowcharts.

Documentation page, next to Architecture. Each chart traces the computation
inside one block (the same path its page shows): rectangles are calculations,
diamonds are decisions or iterations, the bold box is the block's output.
The Full-system chart is not drawn yet.

The charts are Mermaid sources rendered in the browser (Mermaid 10.9.1 from
cdnjs, the same build as the project's flowchart page). On Streamlit with
st.iframe the frame sizes itself to the chart; on older versions the fallback
frame uses the chart's measured height in CHARTS (and scrolls), so update that
height if a chart's text changes a lot.
"""
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

ACCENT = "#285A7A"
ACCENT2 = "#C2703A"

PUMP = r"""flowchart TD
  IN["Inputs<br/>• VFD frequency f (Hz)<br/>• Outlet pressure p (bar)<br/>• Suction pressure (bar)"]

  subgraph A["1 · Shaft speed"]
    a["n = 30·f × 1480/1500 = 29.6·f<br/>(4-pole motor; slip of the Danfoss rated point)"]
  end
  subgraph B["2 · Geometric flow"]
    b["Q_theo = 137 cm³/rev × n × 60 / 10⁶"]
  end
  subgraph C["3 · Internal leakage — grows with pressure"]
    c["Q_leak,60 = Q_theo(1480 rpm) − 11.4 = 0.77 m³/h<br/>Q_leak = 0.77 × p / 60"]
  end
  subgraph D["4 · Delivered flow"]
    d["Q = Q_theo − Q_leak"]
  end
  subgraph E["5 · Power, efficiency, energy"]
    e["shaft power = 16.7 × Q × p / 475<br/>volumetric eff. = Q / Q_theo<br/>specific energy = power / Q"]
  end
  subgraph F["6 · Envelope check (Danfoss p. 24)"]
    f{"speed 700–1500 rpm?<br/>outlet 30–70 bar?<br/>suction ≥ 2 bar?"}
  end
  W["Warning on the page<br/>(60 Hz → 1776 rpm is above 1500)"]

  OUT["KPIs<br/>• Feed flow delivered (m³/h)<br/>• Shaft power absorbed (kW)<br/>• Volumetric efficiency (%)<br/>• Specific energy (kWh/m³)"]

  IN --> a
  a --> b
  b --> c
  c --> d
  d --> e
  e --> OUT
  a --> f
  f -->|no| W
  class OUT out
  classDef out stroke-width:3px;
"""

MEMBRANE = r"""flowchart TD
  IN["Inputs<br/>• Feed pressure Pf (bar)<br/>• Feed salinity Cf (mg/L)<br/>• Feed temperature T (°C)<br/>• Feed flow Qf (m³/h)<br/>• Membrane age (years, from plant records)"]

  subgraph S3["Step 3 · permeabilities — runs ONCE at import"]
    s3["from the ESS standard test (55 bar, 32,000 mg/L, 25 °C, 10 %):<br/>NDPs = Pfs − ΔPe/2 − Δπ<br/>Kw25 = Jws / NDPs<br/>Ks25 = Jws · Cps / Cfcs"]
  end

  subgraph AG["Installed element · salt passage from its age"]
    ag["Ks,min = Ks at the ESS minimum rejection 99.7 % (Step-3 method)<br/>Ks,plant = Ks,min × 1.07^age   (CH9 Table 4, p. 248)<br/>f_sp = Ks,plant / Ks25<br/>Kw is NOT aged (cleaning restores it)"]
  end

  subgraph S5["Step 5 · flows, recovery, β — LIVE SOLVE (iterates)"]
    s5a["start R = 0.10"]
    s5b["Cc = Cf·(1 − R(1−SR)) / (1 − R)<br/>Δπ = π_fc − π_p<br/>NDP = Pf − ΔPe/2 − Δπ − Pp"]
    s5c{"NDP above 0?"}
    s5d["Kw(T) = Kw25 · 1.03^(T−25)<br/>J = Kw(T) · NDP<br/>Qp = J · A / 1000"]
    s5e["J = 0, Qp = 0<br/>(no permeate)"]
    s5f{"R settled?<br/>R_new = Qp / Qf"}
    s5g["then Qc = Qf − Qp<br/>β = Kp · e^(Qp/Qfc)"]
    s5a --> s5b
    s5b --> s5c
    s5c -->|yes| s5d
    s5c -->|no| s5e
    s5d --> s5f
    s5e --> s5f
    s5f -->|"no: R = (R + R_new)/2"| s5b
    s5f -->|yes| s5g
  end

  subgraph S6["Step 6 · permeate quality — LIVE SOLVE"]
    s6["Ks(T) = Ks25 · f_sp · 1.03^(T−25)<br/>Cp = Cfc · Ks(T) / J<br/>rejection = 1 − Cp / Cf"]
  end

  subgraph S7["Step 7 · cross-flow velocity — LIVE SOLVE"]
    s7["Qfc = (Qf + Qc)/2,  w = (A/Le)/2<br/>A_eff = ε·h·w,  vfc = (Qfc/3600) / A_eff"]
  end

  D124["Steps 1, 2 and 4 · design relations<br/>shown at the solved point,<br/>not fed back into the result"]

  OUT["KPIs<br/>• Permeate flow (m³/h) and flux (LMH)<br/>• Permeate TDS (mg/L) and salt rejection (%)<br/>• Recovery (%)<br/>• Brine flow and brine TDS<br/>• NDP, Δπ, β, cross-flow velocity<br/>+ ESS envelope warnings"]

  IN --> s5a
  S3 --> S5
  AG --> S6
  s5g --> s6
  s6 --> s7
  s7 --> OUT
  s7 -.-> D124
  class OUT out
  classDef out stroke-width:3px;
"""

VALVE = r"""flowchart TD
  R["One steady plant reading<br/>• Brine-gauge pressure P_brine (bar)<br/>• Brine flow Q_brine (m³/h)"]

  subgraph K0["0 · Valve resistance from the reading"]
    k["K = P_brine / Q_brine²<br/>(hand-wheel position is not recorded,<br/>so the valve is described by its effect)"]
  end

  IN["Inputs<br/>• Resistance K (bar per (m³/h)²)<br/>• Brine flow Q_b it must pass (m³/h)"]

  subgraph A["1 · Back-pressure developed"]
    a["P_b = K · Q_b²<br/>(holds whether the flow is choked or not)"]
  end
  subgraph B["2 · Equivalent Cv — information only"]
    b["Cv_eq = √(SG / K) / 0.865,  SG = 1.03<br/>not used in any calculation"]
  end
  subgraph C["3 · Rating check"]
    c{"P_b above 100 bar?<br/>(Class 600 body)"}
  end
  W["Warning: valve closed too far"]

  OUT["KPIs<br/>• Back-pressure P_b (bar) — sets the system pressure<br/>• Resistance K<br/>• Equivalent Cv"]

  R --> k
  k --> IN
  IN --> a
  a --> b
  b --> OUT
  a --> c
  c -->|yes| W
  class OUT out
  classDef out stroke-width:3px;
"""

COMPARISON = r"""flowchart TD
  IN["Lab workbook (.xlsx)<br/>one column per experiment"]

  subgraph A["1 · Read the sheet"]
    a["find the header row: 'Exp N' / 'Experiment N'<br/>count the experiments<br/>match each parameter row by its label"]
  end
  subgraph B["2 · Conversions"]
    b["PSI → bar<br/>feed / brine EC under 1000 → read as mS/cm (× 1000)<br/>TDS = EC × k when no salinity row<br/>(k = 0.66 feed and brine, 0.50 permeate)<br/>K = P_brine / Q_brine²"]
  end
  C["3 · User picks one experiment"]
  subgraph D["4 · Simulation inputs"]
    d["from the run: frequency f, resistance K,<br/>feed TDS, feed temperature<br/>membrane age: sheet row, else entered on the page<br/>fixed: ΔP_gauges = 4.48 bar (median, first campaign)"]
  end
  subgraph E["5 · Solve the coupled plant"]
    e1["guess feed pressure P (0.1–82.7 bar)"]
    e2["pump: Qf = flow(f, P)<br/>membrane at P − (ΔP_gauges − ΔPe)/2 → Qp<br/>Qb = Qf − Qp<br/>valve: K · Qb²"]
    e3{"K · Qb² = P − ΔP_gauges ?"}
    e1 --> e2
    e2 --> e3
    e3 -->|"no: bisection on P"| e2
  end
  subgraph F["6 · Lab side"]
    f["measured: pressures, Qp, Qb, TDS<br/>derived: Qf = Qp + Qb, recovery, flux, rejection<br/>from workbook: power, SEC, β"]
  end
  subgraph G["7 · Validity checks for this run"]
    g1{"NDP ≤ 0 ?"}
    g2{"NDP below 10 bar ?"}
    g3{"lab Qf above pump<br/>geometric flow ?"}
  end
  X1["Red: outside the model's range —<br/>no permeate predicted (low K)"]
  X2["Amber: low driving pressure —<br/>large relative errors"]
  X3["Amber: flow reading suspect"]
  subgraph H["8 · Comparison table"]
    h["lab | simulation | sim − lab | 100·(sim − lab)/|lab|<br/>Equation ↓ link on every row"]
  end

  OUT["Page output<br/>• Inputs and fixed values, each with its source<br/>• Lab vs simulation table<br/>• Every simulated value's equation (CH9 Steps 1–7)<br/>• Limits of the simulation"]

  IN --> a
  a --> b
  b --> C
  C --> d
  d --> e1
  e3 -->|yes| f
  f --> g1
  g1 -->|yes| X1
  g1 -->|no| g2
  g2 -->|yes| X2
  g2 -->|no| g3
  g3 -->|yes| X3
  X1 --> g3
  X2 --> g3
  g3 -->|no| h
  X3 --> h
  h --> OUT
  class OUT out
  classDef out stroke-width:3px;
"""


# (tag, title, description, mermaid source, measured height in px)
CHARTS = [
    ("Block 1 · core/pump.py", "Pump — speed → flow → power",
     "Positive-displacement pump: flow is the geometric flow at the motor speed, less an "
     "internal leakage that grows with outlet pressure; power from the Danfoss calc-factor. "
     "Page charts: flow vs speed at the current outlet pressure (dashed above 1500 rpm = "
     "extrapolated) and power vs pressure at the current speed.", PUMP, 1530),
    ("Block 2 · core/membrane.py", "Membrane — CH9 design procedure with the installed element",
     "CH9 steps in report order. Step 3 runs once at import; the live solve is Steps 5 → 6 → 7. "
     "The membrane age sets the salt permeability of the installed element only. Page charts: "
     "flux and rejection vs feed pressure (solid = new element, dashed = installed), flux vs "
     "temperature and vs salinity.", MEMBRANE, 2263),
    ("Block 3 · core/valve.py", "Valve — measured resistance → back-pressure",
     "The hand-wheel position is not measured, so the valve enters by its measured resistance "
     "K. No opening %, Cv curve or cavitation model is assumed. Page charts: back-pressure vs "
     "brine flow at the current K (grey dots = first-campaign runs) and back-pressure vs K at "
     "the current brine flow.", VALVE, 1306),
    ("Block 4 · experiments_page.py + core/experiments.py", "Simulation & experiments comparison",
     "Reads the lab workbook as it is, drives the coupled plant with one experiment's frequency, "
     "valve resistance and feed conditions, and sets the simulated results beside the lab "
     "values with the difference only. Validity checks flag runs the model cannot predict "
     "(low K) or whose flow readings exceed the pump's capacity.", COMPARISON, 3533),
]

_FRAME = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:transparent;font-family:sans-serif}
#c{display:flex;justify-content:center;padding:8px 4px}
.err{color:#B4553A;font-size:13px;white-space:pre-wrap}</style></head>
<body><div id="c"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<script>
const src = __SRC__;
mermaid.initialize({startOnLoad:false, securityLevel:'loose', theme:'neutral',
  themeVariables:{primaryColor:'#FBF9F4', primaryTextColor:'#201E1A',
                  primaryBorderColor:'#285A7A', lineColor:'#6B6558', fontSize:'14px'},
  flowchart:{htmlLabels:true, curve:'linear', nodeSpacing:55, rankSpacing:60,
             useMaxWidth:false}});
mermaid.render('chart', src).then(r => { document.getElementById('c').innerHTML = r.svg; })
  .catch(e => { document.getElementById('c').innerHTML =
    '<div class="err">Diagram failed to render: ' + (e && e.message ? e.message : e) + '</div>'; });
</script></body></html>"""


def _card_head(tag: str, title: str, desc: str) -> None:
    st.markdown(
        f'<div style="margin-top:1.2rem">'
        f'<span style="font-size:12px;font-weight:600;letter-spacing:.04em;'
        f'text-transform:uppercase;color:{ACCENT2}">{tag}</span>'
        f'<h3 style="margin:.15rem 0 .25rem">{title}</h3>'
        f'<p style="opacity:.75;font-size:14.5px;margin:0 0 .4rem;max-width:80ch">{desc}</p>'
        f'</div>',
        unsafe_allow_html=True)


def render() -> None:
    st.header("Logic flowcharts")
    st.caption("Each chart traces the computation inside one block, the same path its page "
               "shows. Rectangles are calculations, diamonds are decisions or iterations, the "
               "bold box is the block's output. Sources in the code: ESS = SWC4 MAX spec sheet, "
               "CH9 = IWA 2021 Ch. 9, Danfoss = APP 11-13 manual, measured = plant runs.")
    st.info("The Full-system chart is not drawn yet. The comparison chart (Block 4, step 5) "
            "already shows the coupled solve it uses.")
    for tag, title, desc, src, height in CHARTS:
        with st.container(border=True):
            _card_head(tag, title, desc)
            html = _FRAME.replace("__SRC__", json.dumps(src))
            if hasattr(st, "iframe"):
                st.iframe(html, height="content")
            else:   # Streamlit before st.iframe
                components.html(html, height=height + 30, scrolling=True)
