"""Valve block — NORITON 1½″ CF8M, Class 600 globe valve (brine throttle).

Corrected framing: the valve is a variable RESISTANCE on the brine line.
In the plant it does not meter a flow from a supplied pressure — it must
pass whatever brine the membrane rejects, and in doing so it CREATES a
back-pressure. That back-pressure sets the system pressure and therefore
the recovery.

  Inputs : opening (% hand-wheel travel, the operator's knob)
           brine flow Q_brine (comes from the membrane / mass balance)
  Output : back-pressure ΔP it develops  (+ its resistance, + cavitation)

  Core law (Cv equation solved for pressure):
           ΔP = ( Q_brine / (0.865 · Cv(opening)) )² · SG

Sanity check built in: fully open (Cv → Cv_max) gives a near-zero
back-pressure, so the system pressure collapses and nothing is produced —
the throttling is what makes the RO work.

Cv and the characteristic are REPRESENTATIVE for a 1½″ globe valve (a
manual BS 1873 valve has no published curve) and are to be calibrated
from plant measurements.

Sources:
  NP    — valve nameplate: NORITON 1½″, CF8M, Class 600
  REP   — representative 1½″ globe value, to be calibrated on site
  CVREF — standard control-valve references (ISA / IEC 60534; Siemens guide)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

REP = ("Representative for a 1½″ globe valve — a manual BS 1873 valve has no "
       "published Cv curve; calibrate from plant measurements")
CVREF = "Standard control-valve references (ISA / IEC 60534; Siemens globe guide)"

KV_FACTOR = 0.865   # Kv = 0.865 · Cv
FF = 0.96           # liquid critical-pressure-ratio factor (water)
PV = 0.04           # bar abs, water vapour pressure near 28 °C
P_ATM = 1.013       # bar, atmospheric (brine discharges to ~atmosphere)


@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    what: str
    source: str


PARAMS: dict[str, Spec] = {
    "Cv_max": Spec(28.0, "—",
                   "Flow coefficient at full open (rated capacity)", REP),
    "rangeability": Spec(50.0, "—",
                         "Equal-percentage rangeability (Cv_max / Cv_min)", CVREF),
    "FL": Spec(0.9, "—",
               "Pressure-recovery factor of a globe valve (sets the cavitation point)", CVREF),
    "SG": Spec(1.03, "—",
               "Brine specific gravity", "Seawater brine ≈ 1.03"),
}

ENVELOPE = {"max_pressure": (100.0, "bar", "Class 600 working pressure")}


def v(key: str) -> float:
    return PARAMS[key].value


# ---------------------------------------------------------------------
# Laws
# ---------------------------------------------------------------------
def cv_at(opening_pct: float) -> float:
    """Equal-percentage characteristic: Cv(x) = Cv_max · R^(x−1), x = fraction
    open. Cv is 0 at the seat (fully closed)."""
    x = max(0.0, min(opening_pct, 100.0)) / 100.0
    if x <= 0.0:
        return 0.0
    return v("Cv_max") * v("rangeability") ** (x - 1.0)


def cavitation_onset() -> float:
    """Back-pressure above which the valve cavitates (derived from the FL choke
    condition, with the brine discharging to ~atmosphere)."""
    fl = v("FL")
    return fl ** 2 * (P_ATM - FF * PV) / (1.0 - fl ** 2)


def back_pressure(brine_flow: float, opening_pct: float, sg: float) -> tuple:
    """Back-pressure the valve develops to pass `brine_flow` at this opening:

        ΔP = ( Q / (0.865 · Cv) )² · SG

    Returns (ΔP, Cv, Kv, resistance). ΔP → ∞ as the valve closes (Cv → 0)."""
    cv = cv_at(opening_pct)
    kv = KV_FACTOR * cv
    if kv <= 0.0:
        return math.inf, 0.0, 0.0, math.inf
    dp = (brine_flow / kv) ** 2 * sg
    resistance = sg / kv ** 2            # ΔP = resistance · Q²
    return dp, cv, kv, resistance


# ---------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------
@dataclass
class ValveResult:
    opening: float
    brine_flow: float
    sg: float
    delta_p: float        # back-pressure produced [bar]
    cv: float
    kv: float
    resistance: float
    cavitating: bool
    kpis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    worked: dict = field(default_factory=dict)


def simulate(opening_pct: float, brine_flow: float, sg: float | None = None) -> ValveResult:
    sg = v("SG") if sg is None else sg
    dp, cv, kv, resistance = back_pressure(brine_flow, opening_pct, sg)
    cavitating = dp > cavitation_onset()

    x = opening_pct / 100.0
    if math.isfinite(dp):
        dp_str = (rf"\Delta P = \left(\frac{{Q}}{{0.865\,C_v}}\right)^2 SG"
                  rf" = \left(\frac{{{brine_flow:.2f}}}{{0.865\times {cv:.2f}}}\right)^2"
                  rf"\times {sg:.2f} = {dp:.1f}\ \mathrm{{bar}}")
    else:
        dp_str = r"\Delta P \to \infty \quad(\text{valve closed — deadhead})"
    worked = {
        "cv": (rf"C_v = C_{{v,max}}\,R^{{x-1}} = {v('Cv_max'):.0f}\times {v('rangeability'):.0f}"
               rf"^{{{x:.2f}-1}} = {cv:.2f}"),
        "dp": dp_str,
    }

    r = ValveResult(opening=opening_pct, brine_flow=brine_flow, sg=sg,
                    delta_p=dp, cv=cv, kv=kv, resistance=resistance,
                    cavitating=cavitating, worked=worked)
    r.kpis = {"back_pressure": dp, "cv": cv, "resistance": resistance,
              "cavitating": cavitating}
    r.warnings = _check(r)
    return r


def _check(r: ValveResult) -> list[str]:
    w = []
    if r.cv <= 0.0:
        w.append("valve fully closed — infinite back-pressure (deadhead). "
                 "Never operate here; the pump would over-pressure the system")
    elif not math.isfinite(r.delta_p) or r.delta_p > ENVELOPE["max_pressure"][0]:
        w.append(f"back-pressure {r.delta_p:.0f} bar exceeds the Class 600 rating "
                 f"(~{ENVELOPE['max_pressure'][0]:.0f} bar) — the valve is closed too far")
    if r.cavitating and math.isfinite(r.delta_p):
        w.append(f"cavitating: the valve drops {r.delta_p:.0f} bar across one seat "
                 f"(onset ~{cavitation_onset():.0f} bar) — expect noise and erosion "
                 f"(CF8M is chosen for this)")
    return w


# ---------------------------------------------------------------------
# Interpretation (calibrate from a measured reading)
# ---------------------------------------------------------------------
def interpret(r: ValveResult, measured: dict | None = None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    msgs.append(("info",
        "The Cv and the equal-percentage shape are representative for a 1½″ globe "
        "valve, not a published curve. Enter a measured (opening, brine flow, "
        "back-pressure) reading to calibrate the real characteristic."))
    if r.cavitating and math.isfinite(r.delta_p):
        msgs.append(("warn",
            "The valve is cavitating — it throttles most of the brine pressure across "
            "one seat. This erodes the trim over time and is why the body is CF8M."))

    if not measured:
        return msgs

    op = measured.get("opening")
    dp = measured.get("back_pressure")
    qm = measured.get("brine_flow")
    if op is not None and dp and qm:
        cv_model = cv_at(op)
        cv_meas = qm / (KV_FACTOR * math.sqrt(max(dp, 1e-6) / r.sg))
        if cv_model > 0:
            gap = (cv_meas - cv_model) / cv_model * 100.0
            if abs(gap) <= 10:
                msgs.append(("ok",
                    f"Measured point implies Cv ≈ {cv_meas:.2f} at {op:.0f}% open, within "
                    f"{gap:+.0f}% of the assumed {cv_model:.2f} — the representative curve fits."))
            else:
                msgs.append(("warn",
                    f"Measured point implies Cv ≈ {cv_meas:.2f} at {op:.0f}% open, {gap:+.0f}% "
                    f"from the assumed {cv_model:.2f}. Collect a few points and recalibrate "
                    f"Cv_max and the characteristic to your valve."))
    return msgs


# ---------------------------------------------------------------------
# Reference curves (back-pressure framing)
# ---------------------------------------------------------------------
def bp_vs_opening(brine_flow, sg=None, lo=12.0, hi=100.0, points=45):
    sg = v("SG") if sg is None else sg
    out = []
    for i in range(points):
        op = lo + (hi - lo) * i / (points - 1)
        dp = back_pressure(brine_flow, op, sg)[0]
        out.append((op, dp if math.isfinite(dp) else None))
    return out


def bp_vs_brineflow(opening_pct, sg=None, lo=0.0, hi=15.0, points=41):
    sg = v("SG") if sg is None else sg
    out = []
    for i in range(points):
        q = lo + (hi - lo) * i / (points - 1)
        dp = back_pressure(q, opening_pct, sg)[0]
        out.append((q, dp if math.isfinite(dp) else None))
    return out
