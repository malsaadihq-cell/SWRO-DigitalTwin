"""System block — the full coupled plant.

This is the digital twin proper: the three blocks run together and the plant
is driven by the only two knobs on site — the VFD frequency and the brine
valve — plus the measured feed conditions.

The valve knob is its measured resistance K (see core/valve.py): the hand-wheel
position is never recorded, so the valve is described by its effect.

Coupling (one unknown: the operating pressure P at the feed gauge):

    pump      : frequency              -> feed flow Q_feed   (fixed, PD pump)
    membrane  : P, Q_feed, Cf, T       -> permeate Qp(P), brine Qb = Q_feed - Qp
    valve     : K, Qb                  -> back-pressure K·Qb²
    closure   : the back-pressure equals the brine-gauge pressure, P - ΔP_gauges

So we solve for the single P where

    K · ( Q_feed - Qp(P) )²  =  P - ΔP_gauges

ΔP_gauges is the MEASURED difference between the feed and brine gauges (median
of Exp 1–9). Where along the skid that loss happens is not known; here it is
treated as a loss between the feed gauge and the valve that does not change the
membrane's own driving pressure (the membrane keeps its ΔPe = 0.2 bar).

Raise K (close the valve) -> higher P -> more permeate -> higher recovery.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import membrane, pump, valve


@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    what: str
    source: str


PARAMS: dict[str, Spec] = {
    "dP_gauges": Spec(4.48, "bar",
                      "Pressure difference between the feed and brine gauges — median of "
                      "Exp 1–9 (range 3.65 – 8.62; Exp 1 is an outlier). Treated as a loss "
                      "between the feed gauge and the valve.",
                      "Measured: RO Operating Readings, Exp 1–9, row 'Feed − Brine Gauge ΔP'"),
}

DP_GAUGES = PARAMS["dP_gauges"].value
ELEMENT_DP = membrane.p("dPe")   # used inside the membrane model only (NDP)
P_MIN, P_MAX = 0.1, 82.7         # search bounds (bar); 82.7 = membrane max


def feed_flow(frequency_hz: float, health: float = 1.0) -> float:
    """Feed flow the PD pump delivers (independent of pressure)."""
    return pump.nominal_flow(pump.rpm_from_frequency(frequency_hz)) * health


def _state(P, resistance, feed_tds, temperature, q_feed, fouling):
    mr = membrane.simulate(P, feed_tds, temperature, q_feed, fouling)
    qb = max(q_feed - mr.permeate_flow, 0.0)
    vr = valve.simulate(resistance, qb)
    residual = vr.delta_p - (P - DP_GAUGES)
    return residual, mr, qb, vr


@dataclass
class SystemResult:
    frequency: float
    valve_resistance: float
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
    converged: bool

    kpis: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    worked: dict = field(default_factory=dict)


def simulate(frequency_hz: float, valve_resistance: float, feed_tds: float,
             temperature: float, health: float = 1.0, fouling: float = 1.0,
             suction: float = 3.0) -> SystemResult:
    q_feed = feed_flow(frequency_hz, health)

    def res(P):
        return _state(P, valve_resistance, feed_tds, temperature, q_feed, fouling)[0]

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

    _, mr, qb, vr = _state(P, valve_resistance, feed_tds, temperature, q_feed, fouling)
    power = pump.shaft_power(q_feed, P)
    qp = mr.permeate_flow
    recovery = (qp / q_feed) if q_feed > 0 else 0.0
    sec = (power / qp) if qp > 0 else math.inf
    K = valve_resistance

    worked = {
        "qfeed": (rf"Q_{{feed}} = Q_{{rated}}\,\frac{{n}}{{1500}}\,h = "
                  rf"{pump.v('rated_flow')}\times\frac{{{pump.rpm_from_frequency(frequency_hz):.0f}}}"
                  rf"{{1500}}\times {health:.2f} = {q_feed:.2f}\ \mathrm{{m^3/h}}"),
        "balance": (rf"Q_{{feed}} = Q_p + Q_b:\quad {q_feed:.2f} = {qp:.2f} + {qb:.2f}"),
        "pressure": (rf"\text{{solve }}P:\ K\,Q_b^2 = P-\Delta P_{{gauges}}"
                     rf"\ \Rightarrow\ {K:.3f}\times {qb:.2f}^2 = {P:.2f} - {DP_GAUGES:.2f}"
                     rf"\ \Rightarrow\ P = {P:.1f}\ \mathrm{{bar}}"),
        "brine_p": (rf"P_b = P - \Delta P_{{gauges}} = {P:.2f} - {DP_GAUGES:.2f}"
                    rf" = {P - DP_GAUGES:.2f}\ \mathrm{{bar}}"),
        "recovery": (rf"R = Q_p/Q_{{feed}} = {qp:.2f}/{q_feed:.2f} = {recovery*100:.1f}\%"),
        "sec": (rf"SEC = P_{{shaft}}/Q_p = {power:.2f}/{qp:.2f} = {sec:.1f}\ \mathrm{{kWh/m^3}}"),
    }

    r = SystemResult(
        frequency=frequency_hz, valve_resistance=K, feed_tds=feed_tds,
        temperature=temperature, operating_pressure=P, feed_flow=q_feed,
        permeate_flow=qp, brine_flow=qb, permeate_tds=mr.permeate_tds,
        brine_tds=mr.brine_tds, recovery=recovery, flux=mr.flux,
        rejection=mr.rejection, sec=sec, power=power,
        valve_back_pressure=vr.delta_p, converged=converged, worked=worked,
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
        w.append("no steady-state pressure balance was found in range — the valve "
                 "resistance may be too high (pressure would exceed limits) or too low")
    if r.operating_pressure > pump.v("outlet_max"):
        w.append(f"operating pressure {r.operating_pressure:.0f} bar exceeds the pump "
                 f"outlet max ({pump.v('outlet_max'):.0f} bar) — open the valve (lower K)")
    for m in mr.warnings:
        w.append("membrane: " + m)
    for m in vr.warnings:
        w.append("valve: " + m)
    return w


# ---------------------------------------------------------------------
# Performance-map sweeps (one knob swept, the plant solved at each point)
# ---------------------------------------------------------------------
K_SWEEP = (0.05, 1.00)     # bar/(m³/h)² — measured 0.106 – 0.357 at 60 Hz; lower Hz needs higher K


def sweep_valve(frequency_hz, feed_tds, temperature, health=1.0, fouling=1.0,
                lo=K_SWEEP[0], hi=K_SWEEP[1], points=34):
    return [simulate(frequency_hz, lo + (hi - lo) * i / (points - 1), feed_tds,
                     temperature, health, fouling) for i in range(points)]


def sweep_frequency(valve_resistance, feed_tds, temperature, health=1.0, fouling=1.0,
                    lo=24.0, hi=60.0, points=37):
    return [simulate(lo + (hi - lo) * i / (points - 1), valve_resistance, feed_tds,
                     temperature, health, fouling) for i in range(points)]
