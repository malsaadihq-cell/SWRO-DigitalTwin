"""Pump block — Danfoss APP 11 / 1500 (code 180B3211).

Design rule for this file: nothing is a bare number. Every characteristic
carries what it means and the exact manual page it comes from, and every
law is a named function whose docstring cites its source. That way the
app can show, next to each result, "this number means X, it came from
page Y, and it was used in this equation" — which is what the examiner
asks for.

Pump identity is confirmed: the manual's Technical-data table (p. 24)
lists code 180B3211 as APP 11 / 1500, and that same code is on the plant
nameplate. So we use that variant's numbers.

Manual = "2 HPP O&M Manual APP 11-13 Pumps" (Danfoss). Page numbers below
are the PDF page numbers of that file.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Sources, with page numbers in the Danfoss manual
P24 = "Danfoss APP 11-13 manual, p. 24 — Technical data table (code 180B3211)"
P25 = "Danfoss APP 11-13 manual, p. 25 — Flow at different rpm"
P26 = "Danfoss APP 11-13 manual, p. 26 — Power requirements (APP 11/1500)"
CH4 = "Project Chapter 4 — instrument survey (50 Hz corresponds to 1500 rpm)"


# ---------------------------------------------------------------------
# A characteristic = value + unit + what it means + where it comes from
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    what: str      # plain-language meaning, for the examiner
    source: str


CHARACTERISTICS: dict[str, Spec] = {
    "displacement": Spec(
        137.0, "cm³/rev",
        "Fluid volume the pump pushes per shaft revolution", P24),
    "rated_flow": Spec(
        11.1, "m³/h",
        "Delivered flow at max speed (1500 rpm) and 60 bar", P24),
    "rated_rpm": Spec(
        1500.0, "rpm",
        "Maximum continuous shaft speed", P24),
    "min_rpm": Spec(
        700.0, "rpm",
        "Minimum continuous shaft speed", P24),
    "outlet_min": Spec(
        30.0, "bar",
        "Lowest allowed discharge pressure", P24),
    "outlet_max": Spec(
        70.0, "bar",
        "Highest allowed discharge pressure (continuous)", P24),
    "inlet_min": Spec(
        2.0, "bar",
        "Lowest allowed suction pressure — below it, cavitation risk", P24),
    "inlet_max": Spec(
        5.0, "bar",
        "Highest allowed suction pressure (continuous)", P24),
    "power_ref": Spec(
        24.0, "kW",
        "Manufacturer shaft power at 1500 rpm & 60 bar — a check point", P24),
    "calc_factor": Spec(
        475.0, "—",
        "Constant in the Danfoss power equation; bundles pump efficiency, "
        "specific to this pump variant", P26),
    "hz_to_rpm": Spec(
        30.0, "rpm/Hz",
        "Converts VFD frequency to shaft speed for this motor", CH4),
}


def spec(key: str) -> Spec:
    return CHARACTERISTICS[key]


def v(key: str) -> float:
    return CHARACTERISTICS[key].value


# ---------------------------------------------------------------------
# The laws. Each returns the number; simulate() also builds the worked
# string so the UI can show "11.1 × 1440/1500 = 10.66", not just the answer.
# ---------------------------------------------------------------------
def rpm_from_frequency(hz: float) -> float:
    """Speed from VFD frequency. Fixed ratio (Chapter 4): rpm = hz × 30."""
    return hz * v("hz_to_rpm")


def theoretical_flow(rpm: float) -> float:
    """Geometric (slip-free) flow of a fixed-displacement pump:

        Q_theo [m³/h] = displacement [cm³/rev] × rpm × 60 / 1e6

    Used only to express volumetric efficiency; not the delivered flow.
    """
    return v("displacement") * rpm * 60.0 / 1e6


def nominal_flow(rpm: float) -> float:
    """Delivered flow, manufacturer flow-vs-rpm law (manual p. 25):

        "The flow/rpm ratio is constant"  ->  Q = Q_rated × rpm / rpm_rated

    This is the straight reference line on the p. 25 chart; it already
    includes the pump's nominal slip at rated conditions.
    """
    return v("rated_flow") * rpm / v("rated_rpm")


def shaft_power(flow_m3h: float, outlet_bar: float) -> float:
    """Absorbed power, Danfoss equation (manual p. 26):

        P [kW] = 16.7 × Q [m³/h] × p_out [bar] / calc_factor

    calc_factor = 475 for APP 11/1500 bundles the pump efficiency.
    (Checks out: 16.7 × 11.4 × 60 / 475 = 24 kW, matching the p. 24 table.)
    """
    return 16.7 * flow_m3h * outlet_bar / v("calc_factor")


# ---------------------------------------------------------------------
# Result of one simulated operating point
# ---------------------------------------------------------------------
@dataclass
class PumpResult:
    frequency_hz: float
    rpm: float
    outlet_pressure: float
    inlet_pressure: float
    health_factor: float          # 1.0 = healthy; < 1 simulates wear

    theoretical_flow: float
    nominal_flow: float
    flow: float                   # delivered = nominal × health

    shaft_power: float
    volumetric_efficiency: float  # delivered / theoretical
    specific_energy: float        # kWh per m³ of feed

    kpis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    worked: dict = field(default_factory=dict)   # LaTeX bodies, no $$


def simulate(frequency_hz: float, outlet_pressure: float,
             health_factor: float = 1.0, inlet_pressure: float = 3.0) -> PumpResult:
    """Solve the pump block for one setting."""
    rpm = rpm_from_frequency(frequency_hz)
    q_theo = theoretical_flow(rpm)
    q_nom = nominal_flow(rpm)
    flow = q_nom * health_factor
    power = shaft_power(flow, outlet_pressure)
    eta_v = (flow / q_theo) if q_theo else 0.0
    sec = (power / flow) if flow else math.inf

    worked = {
        "rpm": rf"n = f \times 30 = {frequency_hz:.1f} \times 30 = {rpm:.0f}\ \mathrm{{rpm}}",
        "flow": (rf"Q = Q_{{rated}}\,\frac{{n}}{{n_{{rated}}}}"
                 rf"\times h = {v('rated_flow')}\times\frac{{{rpm:.0f}}}{{1500}}"
                 rf"\times {health_factor:.2f} = {flow:.2f}\ \mathrm{{m^3/h}}"),
        "power": (rf"P = \frac{{16.7\,Q\,p_{{out}}}}{{k}}"
                  rf" = \frac{{16.7 \times {flow:.2f} \times {outlet_pressure:.1f}}}{{475}}"
                  rf" = {power:.2f}\ \mathrm{{kW}}"),
        "eta": (rf"\eta_v = \frac{{Q}}{{Q_{{theo}}}} = \frac{{{flow:.2f}}}{{{q_theo:.2f}}}"
                rf" = {eta_v*100:.1f}\%"),
        "sec": (rf"e = \frac{{P}}{{Q}} = \frac{{{power:.2f}}}{{{flow:.2f}}}"
                rf" = {sec:.2f}\ \mathrm{{kWh/m^3}}"),
    }

    result = PumpResult(
        frequency_hz=frequency_hz, rpm=rpm, outlet_pressure=outlet_pressure,
        inlet_pressure=inlet_pressure, health_factor=health_factor,
        theoretical_flow=q_theo, nominal_flow=q_nom, flow=flow,
        shaft_power=power, volumetric_efficiency=eta_v, specific_energy=sec,
        worked=worked,
    )
    result.kpis = {
        "flow": flow,
        "shaft_power": power,
        "volumetric_efficiency": eta_v * 100.0,
        "specific_energy": sec,
    }
    result.warnings = _check_limits(rpm, outlet_pressure, inlet_pressure)
    return result


def _check_limits(rpm: float, outlet: float, inlet: float) -> list[str]:
    w = []
    if rpm < v("min_rpm") or rpm > v("rated_rpm"):
        w.append(f"speed {rpm:.0f} rpm is outside the "
                 f"{v('min_rpm'):.0f}–{v('rated_rpm'):.0f} rpm range (manual p. 24)")
    if outlet < v("outlet_min") or outlet > v("outlet_max"):
        w.append(f"outlet pressure {outlet:.1f} bar is outside the "
                 f"{v('outlet_min'):.0f}–{v('outlet_max'):.0f} bar range (manual p. 24)")
    if inlet < v("inlet_min"):
        w.append(f"inlet pressure {inlet:.1f} bar is below the "
                 f"{v('inlet_min'):.0f} bar minimum — cavitation risk (manual p. 24)")
    return w


# ---------------------------------------------------------------------
# Interpretation — reads the operating point and says what it means.
# Levels: "ok" (on spec), "info" (neutral / measurement note), "warn"
# (a real degradation signature). No data is invented; measured values
# come only from what the user typed.
# ---------------------------------------------------------------------
FLOW_TOL = 3.0   # % band around the flow reference counted as "on spec"
POWER_TOL = 5.0  # % band around the power reference counted as "on spec"


def interpret(r: PumpResult, measured: dict | None = None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []

    # --- what the model point itself means -----------------------------
    if r.health_factor < 0.999:
        gap = (1.0 - r.health_factor) * 100.0
        msgs.append(("info",
            f"Simulating wear: the model's delivered flow is {gap:.0f}% below the "
            f"healthy Danfoss reference at {r.rpm:.0f} rpm. On the real pump, a gap "
            f"like this would point to volumetric loss (internal slip or wear)."))
    else:
        msgs.append(("info",
            "At 100% health the model sits on the Danfoss reference by construction. "
            "Enter a measured field reading to compare the real pump against it."))

    if not measured:
        return msgs

    # --- measured flow vs the manufacturer reference -------------------
    f = measured.get("frequency_hz")
    qm = measured.get("flow")
    if f and qm:
        rpm_m = rpm_from_frequency(f)
        ref = nominal_flow(rpm_m)
        gap = (qm - ref) / ref * 100.0 if ref else 0.0
        if abs(gap) <= FLOW_TOL:
            msgs.append(("ok",
                f"Measured flow ({qm:.2f} m³/h) matches the Danfoss reference within "
                f"{gap:+.1f}% at {rpm_m:.0f} rpm — the pump is delivering as specified."))
        elif gap < 0:
            msgs.append(("warn",
                f"Measured flow is {abs(gap):.1f}% BELOW the reference at {rpm_m:.0f} rpm "
                f"→ volumetric loss: internal slip or wear, suction starvation or "
                f"cavitation, or a clogged inlet filter."))
        else:
            msgs.append(("info",
                f"Measured flow is {gap:.1f}% ABOVE the reference. A positive-displacement "
                f"pump cannot exceed its geometric flow, so this usually means a "
                f"measurement issue — check the flow-meter calibration or the rpm reading, "
                f"or recalibrate the reference to this pump."))

    # --- measured power vs the manufacturer reference -----------------
    pm = measured.get("power")
    pp = measured.get("outlet_pressure")
    if pm and pp:
        q_for_power = qm if qm else r.flow
        ref_p = shaft_power(q_for_power, pp)
        gap = (pm - ref_p) / ref_p * 100.0 if ref_p else 0.0
        if abs(gap) <= POWER_TOL:
            msgs.append(("ok",
                f"Measured power ({pm:.2f} kW) matches the Danfoss reference within "
                f"{gap:+.1f}% for this flow and pressure."))
        elif gap > 0:
            msgs.append(("warn",
                f"Measured power is {gap:.1f}% ABOVE the reference for this flow and "
                f"pressure → extra losses (friction, bearing or seal wear) or a higher "
                f"actual pressure than assumed."))
        else:
            msgs.append(("info",
                f"Measured power is {abs(gap):.1f}% below the reference — a lighter load "
                f"than modelled, or a power-reading issue worth checking."))

    return msgs


# ---------------------------------------------------------------------
# Reference curves for plotting (manufacturer lines to compare against)
# ---------------------------------------------------------------------
def flow_reference(points: int = 33) -> list[tuple[float, float]]:
    """Manufacturer flow line (p. 25): (rpm, nominal flow) over the range."""
    lo, hi = v("min_rpm"), v("rated_rpm")
    return [(lo + (hi - lo) * i / (points - 1),
             nominal_flow(lo + (hi - lo) * i / (points - 1)))
            for i in range(points)]


def power_reference(flow_m3h: float, points: int = 33) -> list[tuple[float, float]]:
    """Power line (p. 26) at a fixed flow: (outlet pressure, shaft power)."""
    lo, hi = v("outlet_min"), v("outlet_max")
    return [(lo + (hi - lo) * i / (points - 1),
             shaft_power(flow_m3h, lo + (hi - lo) * i / (points - 1)))
            for i in range(points)]
