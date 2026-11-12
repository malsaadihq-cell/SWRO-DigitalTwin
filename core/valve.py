"""Valve block — brine globe valve 198-VBR-001 (nameplate: NORITON 1½″, CF8M, Class 600).

The valve is a variable RESISTANCE on the brine line. It must pass whatever
brine the membrane rejects, and in doing so it creates a back-pressure. That
back-pressure sets the system pressure and therefore the recovery.

Why there is no opening / Cv curve here
---------------------------------------
The valve is turned by hand and its position is never measured. A law that
maps "% opening" to pressure would need a Cv curve, a trim characteristic and
a pressure-recovery factor — none of which exist for this valve. So the valve
is described by the one thing the plant does measure: its EFFECT.

  Input  : resistance K   [bar per (m³/h)²]  — what the hand-wheel was set to,
                                               expressed by its effect
           brine flow Q   [m³/h]             — from the membrane / mass balance
  Output : back-pressure  P_b = K · Q²   [bar gauge]  (brine discharges to ~atm)

  Measured from any run:  K = P_brine / Q_brine²

P ∝ Q² holds for a throttling valve whether the flow is choked or not, so K
carries Cv, the trim shape and any cavitation effect inside one measured
number. The test of the law needs no position measurement: hold the hand-wheel
still, change the VFD frequency, and K should stay roughly constant.

Sources:
  NP   — valve nameplate: NORITON 1½″, CF8M, Class 600 (tag 198-VBR-001)
  EXP  — RO Operating Readings, Exp 1–9 (experiments_Data workbook)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

NP = "Valve nameplate: NORITON 1½″, CF8M, Class 600 (tag 198-VBR-001)"
EXP = "Measured: RO Operating Readings, Exp 1–9 (K = brine pressure / brine flow²)"

KV_FACTOR = 0.865   # Kv = 0.865 · Cv — used only to express K as an equivalent Cv


@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    what: str
    source: str


PARAMS: dict[str, Spec] = {
    "K_ref": Spec(0.231, "bar/(m³/h)²",
                  "Reference resistance — median of the 9 measured runs "
                  "(range 0.106 – 0.357)", EXP),
    "SG": Spec(1.03, "—",
               "Brine specific gravity (only to express K as an equivalent Cv)",
               "Seawater brine ≈ 1.03"),
    "rating": Spec(100.0, "bar",
                   "Body pressure rating, Class 600", NP),
}

ENVELOPE = {"max_pressure": (PARAMS["rating"].value, "bar", "Class 600 working pressure")}


def v(key: str) -> float:
    return PARAMS[key].value


# ---------------------------------------------------------------------
# Laws
# ---------------------------------------------------------------------
def back_pressure(brine_flow: float, resistance: float) -> float:
    """Back-pressure the valve develops to pass `brine_flow`:

        P_b = K · Q²        [bar gauge]
    """
    return resistance * brine_flow ** 2


def resistance_from_reading(brine_pressure: float, brine_flow: float) -> float:
    """Measured resistance from one steady reading:  K = P_b / Q²."""
    if brine_flow <= 0:
        return math.inf
    return brine_pressure / brine_flow ** 2


def equivalent_cv(resistance: float, sg: float | None = None) -> float:
    """K expressed as an equivalent flow coefficient, for comparison with valve
    catalogues only:  K = SG / (0.865·Cv)²  →  Cv = √(SG/K) / 0.865.
    Not used in any calculation."""
    sg = v("SG") if sg is None else sg
    if resistance <= 0:
        return math.inf
    return math.sqrt(sg / resistance) / KV_FACTOR


# ---------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------
@dataclass
class ValveResult:
    resistance: float     # K [bar/(m³/h)²]
    brine_flow: float     # Q [m³/h]
    delta_p: float        # back-pressure produced [bar]
    cv_equivalent: float  # K expressed as Cv (information only)
    kpis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    worked: dict = field(default_factory=dict)


def simulate(resistance: float, brine_flow: float) -> ValveResult:
    dp = back_pressure(brine_flow, resistance)
    cv_eq = equivalent_cv(resistance)
    worked = {
        "dp": (rf"P_b = K\,Q_b^2 = {resistance:.3f}\times {brine_flow:.2f}^2"
               rf" = {dp:.2f}\ \mathrm{{bar}}"),
        "k": (r"K = \frac{P_{b,\,measured}}{Q_{b,\,measured}^2}"
              r"\quad(\text{set from a reading; the hand-wheel position is not measured})"),
        "cv": (rf"C_{{v,eq}} = \frac{{\sqrt{{SG/K}}}}{{0.865}} = "
               rf"\frac{{\sqrt{{{v('SG'):.2f}/{resistance:.3f}}}}}{{0.865}} = {cv_eq:.2f}"
               r"\quad(\text{information only})"),
    }
    r = ValveResult(resistance=resistance, brine_flow=brine_flow, delta_p=dp,
                    cv_equivalent=cv_eq, worked=worked)
    r.kpis = {"back_pressure": dp, "resistance": resistance, "cv_equivalent": cv_eq}
    r.warnings = _check(r)
    return r


def _check(r: ValveResult) -> list[str]:
    w = []
    if r.delta_p > ENVELOPE["max_pressure"][0]:
        w.append(f"back-pressure {r.delta_p:.0f} bar exceeds the Class 600 rating "
                 f"(~{ENVELOPE['max_pressure'][0]:.0f} bar) — the valve is closed too far")
    return w


# ---------------------------------------------------------------------
# Interpretation of a measured reading (no pass/fail — it gives the K to use)
# ---------------------------------------------------------------------
def interpret(r: ValveResult, measured: dict | None = None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = [("info",
        "K is the valve's measured resistance. The hand-wheel position is not "
        "recorded, so the valve is described by its effect: K = brine pressure ÷ "
        "brine flow². Enter a reading below to get the K it implies.")]
    if not measured:
        return msgs
    dp, qm = measured.get("back_pressure"), measured.get("brine_flow")
    if dp and qm:
        k_meas = resistance_from_reading(dp, qm)
        msgs.append(("info",
            f"This reading implies K = {dp:.2f} / {qm:.2f}² = {k_meas:.3f} bar/(m³/h)² "
            f"(the knob is at {r.resistance:.3f}). Set the knob to {k_meas:.3f} to "
            f"reproduce that hand-wheel position."))
    return msgs


# ---------------------------------------------------------------------
# Reference curves
# ---------------------------------------------------------------------
def bp_vs_brineflow(resistance, lo=0.0, hi=20.0, points=41):
    return [(q, back_pressure(q, resistance))
            for q in (lo + (hi - lo) * i / (points - 1) for i in range(points))]


def bp_vs_resistance(brine_flow, lo=0.05, hi=1.0, points=46):
    return [(k, back_pressure(brine_flow, k))
            for k in (lo + (hi - lo) * i / (points - 1) for i in range(points))]
