"""Pump block — Danfoss APP 11 / 1500 (code 180B3211).

Design rule for this file: nothing is a bare number. Every characteristic
carries the exact place in the Danfoss manual it came from, and every law
is a named function whose docstring quotes the source. That way the app
can show — next to each result — "this number came from here, using this
equation", which is exactly what the examiner asks for.

Pump identity is confirmed: the manual's Technical-data table lists
code 180B3211 as APP 11 / 1500, and that same code number is on the
plant nameplate (your Figure/photo). So we use that variant's numbers.

Sources used below:
  DS§3  — Data sheet, section 3 "Technical data" (per-variant table)
  DS§5  — Data sheet, section 5 "Flow at different rpm" (flow law)
  DS§7  — Data sheet, section 7 "Power requirements" (power equation)
  CH4   — Project Chapter 4 (VFD frequency <-> speed mapping)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DS3 = "Danfoss APP 11-13 data sheet, §3 Technical data (code 180B3211)"
DS5 = "Danfoss APP 11-13 data sheet, §5 Flow at different rpm"
DS7 = "Danfoss APP 11-13 data sheet, §7 Power requirements (APP 11/1500)"
CH4 = "Project Chapter 4 (50 Hz ↔ 1500 rpm)"


# ---------------------------------------------------------------------
# A characteristic = value + unit + where it comes from
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    source: str


CHARACTERISTICS: dict[str, Spec] = {
    "displacement": Spec(137.0, "cm³/rev", DS3),
    "rated_flow":   Spec(11.1, "m³/h", DS3 + " — rated flow at 1500 rpm, 60 bar"),
    "rated_rpm":    Spec(1500.0, "rpm", DS3),
    "min_rpm":      Spec(700.0, "rpm", DS3),
    "outlet_min":   Spec(30.0, "bar", DS3),
    "outlet_max":   Spec(70.0, "bar", DS3),
    "inlet_min":    Spec(2.0, "bar", DS3),
    "inlet_max":    Spec(5.0, "bar", DS3),
    "power_ref":    Spec(24.0, "kW", DS3 + " — power at 1500 rpm, 60 bar"),
    "calc_factor":  Spec(475.0, "—", DS7),
    "hz_to_rpm":    Spec(30.0, "rpm/Hz", CH4),
}


def spec(key: str) -> Spec:
    return CHARACTERISTICS[key]


def v(key: str) -> float:
    return CHARACTERISTICS[key].value


# ---------------------------------------------------------------------
# The laws. Each returns the number AND the worked string, so the UI can
# show "11.1 × 1440/1500 = 10.66", not just the answer.
# ---------------------------------------------------------------------
def rpm_from_frequency(hz: float) -> float:
    """Speed from VFD frequency. Fixed ratio (CH4): rpm = hz × 30."""
    return hz * v("hz_to_rpm")


def theoretical_flow(rpm: float) -> float:
    """Geometric (slip-free) flow of a fixed-displacement pump:

        Q_theo [m³/h] = displacement [cm³/rev] × rpm × 60 / 1e6

    Used only to express volumetric efficiency; not the delivered flow.
    """
    return v("displacement") * rpm * 60.0 / 1e6


def nominal_flow(rpm: float) -> float:
    """Delivered flow, manufacturer flow-vs-rpm law (DS§5):

        "The flow/rpm ratio is constant"  ->  Q = Q_rated × rpm / rpm_rated

    This is the straight reference line on the DS§5 chart; it already
    includes the pump's nominal slip at rated conditions.
    """
    return v("rated_flow") * rpm / v("rated_rpm")


def shaft_power(flow_m3h: float, outlet_bar: float) -> float:
    """Absorbed power, Danfoss equation (DS§7):

        P [kW] = 16.7 × Q [m³/h] × p_out [bar] / calc_factor

    calc_factor = 475 for APP 11/1500 bundles the pump efficiency.
    (Checks out: 16.7 × 11.4 × 60 / 475 = 24 kW, matching the DS table.)
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
    # human-readable worked substitutions (LaTeX bodies, no $$)
    worked: dict = field(default_factory=dict)


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
                 f"{v('min_rpm'):.0f}–{v('rated_rpm'):.0f} rpm range ({DS3})")
    if outlet < v("outlet_min") or outlet > v("outlet_max"):
        w.append(f"outlet pressure {outlet:.1f} bar is outside the "
                 f"{v('outlet_min'):.0f}–{v('outlet_max'):.0f} bar range ({DS3})")
    if inlet < v("inlet_min"):
        w.append(f"inlet pressure {inlet:.1f} bar is below the "
                 f"{v('inlet_min'):.0f} bar minimum — cavitation risk ({DS3})")
    return w


# ---------------------------------------------------------------------
# Reference curves for plotting (manufacturer lines to compare against)
# ---------------------------------------------------------------------
def flow_reference(points: int = 33) -> list[tuple[float, float]]:
    """Manufacturer flow line (DS§5): (rpm, nominal flow) over the range."""
    lo, hi = v("min_rpm"), v("rated_rpm")
    return [(lo + (hi - lo) * i / (points - 1),
             nominal_flow(lo + (hi - lo) * i / (points - 1)))
            for i in range(points)]


def power_reference(flow_m3h: float, points: int = 33) -> list[tuple[float, float]]:
    """Power line (DS§7) at a fixed flow: (outlet pressure, shaft power)."""
    lo, hi = v("outlet_min"), v("outlet_max")
    return [(lo + (hi - lo) * i / (points - 1),
             shaft_power(flow_m3h, lo + (hi - lo) * i / (points - 1)))
            for i in range(points)]
