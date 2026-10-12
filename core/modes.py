"""Operating modes — advisory presets that choose the two knobs.

Each mode prioritises a goal and recommends a VFD frequency and a valve
opening within the plant limits. The twin suggests; the operator sets the
physical knobs. This is the "optimal operating conditions" layer of the
project, built on the system sweeps.
"""
from __future__ import annotations

from . import membrane, pump
from . import system as S

PRESSURE_MAX = pump.v("outlet_max")                 # 70 bar (pump continuous)
BRINE_MIN = membrane.ENVELOPE["min_brine_flow"][0]  # 2.7 m³/h

MODE_NAMES = ["Manual", "Balanced", "Max product", "Eco", "Gentle", "Target"]

GOALS = {
    "Manual": "You set the frequency and the valve yourself.",
    "Balanced": "A safe reference operating point (~10 % recovery) for normal running.",
    "Max product": "The most permeate the plant can make within its limits — at the cost "
                   "of higher pressure, stronger cavitation and more concentrated brine "
                   "(scaling risk).",
    "Eco": "The lowest specific energy — fewest kWh per m³ of product.",
    "Gentle": "Lower flux and recovery to protect the membrane — less scaling/fouling and "
              "gentler on the valve — at the cost of more energy and less product.",
    "Target": "Hit a recovery you choose; the twin finds the knobs that reach it.",
}


def feasible(r: S.SystemResult) -> bool:
    """Within the plant's hard limits (cavitation is a wear note, not a blocker)."""
    return (r.permeate_flow > 1e-3
            and r.operating_pressure <= PRESSURE_MAX + 0.5
            and r.brine_flow >= BRINE_MIN
            and (r.brine_flow / r.permeate_flow) >= 5.0)


def _fine_valve(freq, tds, T, lo=12.0, hi=60.0, n=49):
    return [S.simulate(freq, lo + (hi - lo) * i / (n - 1), tds, T) for i in range(n)]


def _target_recovery(freq, target_R, tds, T):
    # recovery increases as the valve closes -> bisect on the opening
    lo, hi = 12.0, 100.0
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        if S.simulate(freq, mid, tds, T).recovery > target_R:
            lo = mid
        else:
            hi = mid
    r = S.simulate(freq, 0.5 * (lo + hi), tds, T)
    note = ""
    if not feasible(r):
        feas = [x for x in _fine_valve(freq, tds, T) if feasible(x)]
        if feas:
            r = max(feas, key=lambda x: x.recovery)
            note = (f"target {target_R*100:.0f} % is beyond the limits — showing the highest "
                    f"feasible recovery ({r.recovery*100:.1f} %).")
        else:
            note = "no feasible operating point at these feed conditions."
    return r, note


def recommend(mode, tds, T, target_pct=10.0):
    """Return (frequency, valve_opening, result, note) for the chosen mode."""
    if mode == "Max product":
        feas = [r for r in _fine_valve(50.0, tds, T) if feasible(r)]
        r = max(feas, key=lambda x: x.permeate_flow) if feas else S.simulate(50.0, 25.0, tds, T)
        return r.frequency, r.valve_opening, r, ("" if feas else "no feasible point found.")
    if mode == "Eco":
        feas = [r for r in _fine_valve(48.0, tds, T) if feasible(r)]
        r = min(feas, key=lambda x: x.sec) if feas else S.simulate(48.0, 25.0, tds, T)
        return r.frequency, r.valve_opening, r, ("" if feas else "no feasible point found.")
    if mode == "Gentle":
        r, note = _target_recovery(44.0, 0.06, tds, T)
        return r.frequency, r.valve_opening, r, note
    if mode == "Target":
        r, note = _target_recovery(48.0, max(0.01, target_pct / 100.0), tds, T)
        return r.frequency, r.valve_opening, r, note
    # Balanced (default)
    r, note = _target_recovery(48.0, 0.10, tds, T)
    return r.frequency, r.valve_opening, r, note
