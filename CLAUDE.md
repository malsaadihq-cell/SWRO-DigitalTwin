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
- Pump: Danfoss APP 11 / 1500 (axial-piston positive-displacement)
  - D = 137 cm³/rev, Q_rated = 11.1 m³/h at 1500 rpm, k = 475
- Membrane: Hydranautics SWC4 MAX (single element, 8"×40", 40.9 m²)
  - SR = 99.8%, Kw ≈ 0.99 L/m²·bar·h, Ks ≈ 0.056 L/m²·h (at 25°C)
- Valve: brine outlet 198-VBR-001 (variable Cv)
- Operating target: Cf = 41,000 mg/L, T = 25 °C, R ≈ 10%

## Repository layout
- `core/` — physics models, each block self-contained
  - `pump.py`, `membrane.py`, `valve.py` — standalone component models
  - `system.py` — couples the three; solves the single operating pressure
  - `modes.py` — operating-mode definitions
- `*_page.py` — Streamlit UI for each block
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
- Add new dependencies without updating `requirements.txt`
