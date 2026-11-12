# SWRO Digital Twin — Pilot Plant (Water Research Center, Rabigh)

## Project goal
Phase-1 digital twin of a pilot seawater reverse osmosis plant with a 
SINGLE membrane element. Streamlit app with three physical blocks 
(pump, membrane, valve) coupled through a system module that solves 
the operating feed pressure.

## Primary reference
Salinas-Rodríguez et al., "Process design of reverse osmosis systems",
IWA Publishing 2021, **Chapter 9** (abbreviated CH9 in code comments).
This is the authoritative source for all RO equations, iteration
logic, and design checks. Any deviation from CH9 must be flagged.

The CH9 worked example (72-element, 6-per-vessel, 40% recovery plant)
is NOT our plant. We are a single element at R≈10%. Only the 
single-element solution-diffusion laws apply.

## Hardware
- Pump: Danfoss APP 11 / 1500 (axial-piston positive-displacement, code 180B3211)
  - D = 137 cm³/rev, Q_rated = 11.4 m³/h at the rated point (1480 rpm, 60 bar),
    calc factor k = 475, max continuous speed 1500 rpm
  - Delivered flow = D·n − leakage; leakage 0.77 m³/h at 60 bar, ∝ pressure
  - 4-pole motor, 30·f synchronous, slip 1480/1500 → 29.6·f; at 60 Hz ≈ 1776 rpm
    (above the 1500 rpm max — flagged by the model)
- Membrane: Hydranautics SWC4 MAX (single element, 8"×40", 40.9 m²)
  - SR = 99.8% (99.7% min), Kw ≈ 0.99 L/m²·bar·h, Ks ≈ 0.056 L/m²·h (at 25°C)
  - Installed element is 5 years old (end-of-life element on test): the
    system model uses Ks at 99.7% aged 10%/yr (CH9 Table 4) → ×2.42
  - Max pressure drop per element 15 psi (≈1.0 bar)
- Valve: brine outlet 198-VBR-001 (NORITON 1½″, CF8M, Class 600), turned by
  hand, position NOT measured → described by its measured resistance
  K = P_brine / Q_brine² (bar per (m³/h)²); no Cv curve is assumed
- Gauges: feed = pump discharge ("HP discharge PG"), brine = brine strainer;
  measured gap between them ≈ 4.5 bar (median Exp 1–9)
- Operating target: Cf = 41,000 mg/L, T = 25 °C, R ≈ 10%

## Repository layout
- `core/` — physics models, each block self-contained
  - `pump.py`, `membrane.py`, `valve.py` — standalone component models
  - `system.py` — couples the three; solves the single operating pressure
  - `modes.py` — operating-mode definitions
  - `experiments.py` — reads the lab workbook (sheet "Readings")
- `*_page.py` — Streamlit UI for each block; `experiments_page.py` is
  "Full system - with Experiments" (lab vs simulation)
- `app.py` — main Streamlit entry point
- `schematic.py` — P&ID-style flow diagram

## Coding conventions
- Every physical constant is a `Spec(value, unit, what, source)`, never a bare number
- Every physics function has a docstring citing the CH9 page it comes from
- Source tags: `ESS` = Hydranautics spec sheet, `CH9` = IWA 2021 Ch. 9,
  `Danfoss` = pump manufacturer manual
- Use SI units internally; convert only at the UI layer

## Run
    pip install -r requirements.txt
    streamlit run app.py

## Do not
- Change physics constants without updating the `source` field and 
  stating the new reference
- Replace the single-element formulation with the multi-element plant
  formulation from CH9 — our plant is one element
- Fit model parameters to the same experiments used to judge the model
- Add new dependencies without updating `requirements.txt`
