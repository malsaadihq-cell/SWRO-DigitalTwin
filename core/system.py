"""System block — the full coupled plant.

This is the digital twin proper: the three blocks run together and the plant
is driven by the only two knobs on site — the VFD frequency and the brine-
valve opening — plus the measured feed conditions.

Coupling (one unknown: the operating pressure P at the membrane feed):

    pump      : frequency              -> feed flow Q_feed   (fixed, PD pump)
    membrane  : P, Q_feed, Cf, T       -> permeate Qp(P), brine Qb = Q_feed - Qp
    valve     : opening, Qb            -> back-pressure it develops
    closure   : the back-pressure must equal the brine pressure, P - ΔP_element

So we solve for the single P where

    valve_back_pressure( Q_feed - Qp(P), opening )  =  P - ΔP_element

Close the valve -> more back-pressure -> higher P -> more permeate -> higher
recovery. Open it fully -> ~0 back-pressure -> P collapses -> no product.

The plant KPIs reported are the four the project targets: recovery, permeate
flux, salt rejection and specific energy (SEC).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import membrane, pump, valve

ELEMENT_DP = membrane.p("dPe")   # feed -> brine pressure drop across the element
P_MIN, P_MAX = 0.1, 82.7         # search bounds (bar); 82.7 = membrane max


def feed_flow(frequency_hz: float, health: float = 1.0) -> float:
    """Feed flow the PD pump delivers (independent of pressure)."""
    return pump.nominal_flow(pump.rpm_from_frequency(frequency_hz)) * health


def _state(P, opening, feed_tds, temperature, q_feed, fouling):
    mr = membrane.simulate(P, feed_tds, temperature, q_feed, fouling)
    qb = max(q_feed - mr.permeate_flow, 0.0)
    vr = valve.simulate(opening, qb)
    vbp = vr.delta_p if math.isfinite(vr.delta_p) else 1.0e4
    residual = vbp - (P - ELEMENT_DP)
    return residual, mr, qb, vr


@dataclass
class SystemResult:
    frequency: float
    valve_opening: float
    feed_tds: float
    temperature: float

    operating_pressure: float
    feed_flow: float
    permeate_flow: float
    brine_flow: float
    permeate_tds: float
    brine_tds: float

    recovery: float
    flux: float
    rejection: float
    sec: float
    power: float

    valve_back_pressure: float
    cavitating: bool
    converged: bool

    kpis: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    worked: dict = field(default_factory=dict)


def simulate(frequency_hz: float, valve_opening: float, feed_tds: float,
             temperature: float, health: float = 1.0, fouling: float = 1.0,
             suction: float = 3.0) -> SystemResult:
    q_feed = feed_flow(frequency_hz, health)

    def res(P):
        return _state(P, valve_opening, feed_tds, temperature, q_feed, fouling)[0]

    lo, hi = P_MIN, P_MAX
    flo, fhi = res(lo), res(hi)
    converged = True
    if flo == 0:
        P = lo
    elif flo * fhi > 0:                     # no balance in range
        P = lo if abs(flo) < abs(fhi) else hi
        converged = False
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            fm = res(mid)
            if abs(fm) < 1e-4 or (hi - lo) < 1e-4:
                break
            if flo * fm < 0:
                hi = mid
            else:
                lo, flo = mid, fm
        P = 0.5 * (lo + hi)

    _, mr, qb, vr = _state(P, valve_opening, feed_tds, temperature, q_feed, fouling)
    power = pump.shaft_power(q_feed, P)
    qp = mr.permeate_flow
    recovery = (qp / q_feed) if q_feed > 0 else 0.0
    sec = (power / qp) if qp > 0 else math.inf

    worked = {
        "qfeed": (rf"Q_{{feed}} = Q_{{rated}}\,\frac{{n}}{{1500}}\,h = "
                  rf"{pump.v('rated_flow')}\times\frac{{{pump.rpm_from_frequency(frequency_hz):.0f}}}"
                  rf"{{1500}}\times {health:.2f} = {q_feed:.2f}\ \mathrm{{m^3/h}}"),
        "balance": (rf"Q_{{feed}} = Q_p + Q_b:\quad {q_feed:.2f} = {qp:.2f} + {qb:.2f}"),
        "pressure": (rf"\text{{solve }}P:\ \Delta P_{{valve}}(Q_b,\,\text{{open}}) = P-\Delta P_{{el}}"
                     rf"\ \Rightarrow\ P = {P:.1f}\ \mathrm{{bar}}"),
        "recovery": (rf"R = Q_p/Q_{{feed}} = {qp:.2f}/{q_feed:.2f} = {recovery*100:.1f}\%"),
        "sec": (rf"SEC = P_{{shaft}}/Q_p = {power:.2f}/{qp:.2f} = {sec:.1f}\ \mathrm{{kWh/m^3}}"),
    }

    r = SystemResult(
        frequency=frequency_hz, valve_opening=valve_opening, feed_tds=feed_tds,
        temperature=temperature, operating_pressure=P, feed_flow=q_feed,
        permeate_flow=qp, brine_flow=qb, permeate_tds=mr.permeate_tds,
        brine_tds=mr.brine_tds, recovery=recovery, flux=mr.flux,
        rejection=mr.rejection, sec=sec, power=power,
        valve_back_pressure=vr.delta_p, cavitating=vr.cavitating,
        converged=converged, worked=worked,
    )
    r.kpis = {
        "recovery": recovery * 100.0, "flux": mr.flux,
        "rejection": mr.rejection * 100.0, "sec": sec,
        "operating_pressure": P, "power": power,
        "permeate_flow": qp, "brine_flow": qb,
    }
    r.warnings = _warnings(r, mr, vr)
    return r


def _warnings(r, mr, vr):
    w = []
    if not r.converged:
        w.append("no steady-state pressure balance was found in range — the valve may "
                 "be closed too far (pressure would exceed limits) or fully open")
    if r.operating_pressure > pump.v("outlet_max"):
        w.append(f"operating pressure {r.operating_pressure:.0f} bar exceeds the pump "
                 f"outlet max ({pump.v('outlet_max'):.0f} bar) — close the valve less")
    # carry the block-level flags up
    for m in mr.warnings:
        w.append("membrane: " + m)
    if vr.cavitating and math.isfinite(vr.delta_p):
        w.append("valve: cavitating (throttling most of the pressure across one seat)")
    return w


# ---------------------------------------------------------------------
# Performance-map sweeps (one knob swept, the plant solved at each point)
# ---------------------------------------------------------------------
def sweep_valve(frequency_hz, feed_tds, temperature, health=1.0, fouling=1.0,
                lo=10.0, hi=100.0, points=34):
    out = []
    for i in range(points):
        op = lo + (hi - lo) * i / (points - 1)
        r = simulate(frequency_hz, op, feed_tds, temperature, health, fouling)
        out.append(r)
    return out


def sweep_frequency(valve_opening, feed_tds, temperature, health=1.0, fouling=1.0,
                    lo=24.0, hi=50.0, points=27):
    out = []
    for i in range(points):
        f = lo + (hi - lo) * i / (points - 1)
        r = simulate(f, valve_opening, feed_tds, temperature, health, fouling)
        out.append(r)
    return out
