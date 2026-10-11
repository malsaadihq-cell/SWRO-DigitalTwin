"""Valve block — NORITON 1½″ CF8M, Class 600 globe valve (brine throttle).

This is the manual hand-wheel globe valve on the brine line (tag 198-VBR-001)
that sets the recovery. It is an isolation/throttling valve to BS 1873 /
API 623, NOT a control valve, so the manufacturer publishes no Cv-vs-opening
curve. The values here are therefore REPRESENTATIVE for a 1½″ globe valve and
are meant to be calibrated from plant measurements (brine flow at known
hand-wheel positions and pressure drop) — the same path as Kw/Ks.

Sources:
  NP    — valve nameplate: NORITON 1½″, CF8M, Class 600
  REP   — representative 1½″ globe value, to be calibrated on site
  CVREF — standard control-valve references (ISA / IEC 60534; Siemens
          "Globe and Ball Valves" sizing guide)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

NP = "Valve nameplate (NORITON 1½″ CF8M, Class 600)"
REP = ("Representative for a 1½″ globe valve — a manual BS 1873 valve has no "
       "published Cv curve; calibrate from plant measurements")
CVREF = "Standard control-valve references (ISA / IEC 60534; Siemens globe guide)"

# internal constants
KV_FACTOR = 0.865   # Kv = 0.865 · Cv  (US→metric unit conversion)
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
               "Pressure-recovery factor of a globe valve (sets the choke point)", CVREF),
    "SG": Spec(1.03, "—",
               "Brine specific gravity", "Seawater brine ≈ 1.03"),
}

ENVELOPE = {
    "max_pressure": (100.0, "bar", "Class 600 working pressure"),
}


def v(key: str) -> float:
    return PARAMS[key].value


# ---------------------------------------------------------------------
# Laws
# ---------------------------------------------------------------------
def cv_at(opening_pct: float) -> float:
    """Equal-percentage characteristic (CVREF):

        Cv(x) = Cv_max · R^(x−1),   x = opening fraction (0…1)

    Cv is taken as 0 at the seat (fully closed).
    """
    x = max(0.0, min(opening_pct, 100.0)) / 100.0
    if x <= 0.0:
        return 0.0
    return v("Cv_max") * v("rangeability") ** (x - 1.0)


def choke_dp(delta_p: float) -> float:
    """Choked-pressure-drop limit (CVREF). The brine valve drops the whole
    brine pressure to ~atmosphere, so P1 ≈ ΔP + atmospheric and

        ΔP_choked = FL² · (P1,abs − FF·Pv)

    Above this the flow saturates (cavitation / flashing)."""
    p1_abs = delta_p + P_ATM
    return v("FL") ** 2 * (p1_abs - FF * PV)


def flow(opening_pct: float, delta_p: float, sg: float) -> tuple:
    """Brine flow passed [m³/h] = Kv · √(ΔP_eff / SG),  Kv = 0.865·Cv.
    Returns (Q, Cv, Kv, choked, ΔP_eff)."""
    cv = cv_at(opening_pct)
    kv = KV_FACTOR * cv
    dp_ch = choke_dp(delta_p)
    choked = delta_p > dp_ch
    dp_eff = min(delta_p, dp_ch)
    q = kv * math.sqrt(max(dp_eff, 0.0) / sg)
    return q, cv, kv, choked, dp_eff


# ---------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------
@dataclass
class ValveResult:
    opening: float
    delta_p: float
    sg: float
    brine_flow: float
    cv: float
    kv: float
    choked: bool
    dp_eff: float
    kpis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    worked: dict = field(default_factory=dict)


def simulate(opening_pct: float, delta_p: float, sg: float | None = None) -> ValveResult:
    sg = v("SG") if sg is None else sg
    q, cv, kv, choked, dp_eff = flow(opening_pct, delta_p, sg)
    dp_ch = choke_dp(delta_p)

    x = opening_pct / 100.0
    worked = {
        "cv": (rf"C_v = C_{{v,max}}\,R^{{x-1}} = {v('Cv_max'):.0f}\times {v('rangeability'):.0f}"
               rf"^{{{x:.2f}-1}} = {cv:.2f}"),
        "choke": (rf"\Delta P_{{choked}} = F_L^2(P_1 - F_F P_v) = {v('FL'):.2f}^2"
                  rf"\times({delta_p:.1f}+1.0-0.04) = {dp_ch:.1f}\ \mathrm{{bar}}"),
        "q": (rf"Q = 0.865\,C_v\sqrt{{\Delta P_{{eff}}/SG}} = 0.865\times {cv:.2f}"
              rf"\times\sqrt{{{dp_eff:.1f}/{sg:.2f}}} = {q:.2f}\ \mathrm{{m^3/h}}"),
    }

    r = ValveResult(opening=opening_pct, delta_p=delta_p, sg=sg, brine_flow=q,
                    cv=cv, kv=kv, choked=choked, dp_eff=dp_eff, worked=worked)
    r.kpis = {"brine_flow": q, "cv": cv, "kv": kv, "dp_eff": dp_eff,
              "choked": choked}
    r.warnings = _check(r)
    return r


def _check(r: ValveResult) -> list[str]:
    w = []
    if r.delta_p > ENVELOPE["max_pressure"][0]:
        w.append(f"pressure drop {r.delta_p:.0f} bar is above the Class 600 "
                 f"working pressure (~{ENVELOPE['max_pressure'][0]:.0f} bar)")
    if r.choked:
        w.append(f"choked / cavitating flow: the full brine pressure is dropped "
                 f"across one valve (ΔP {r.delta_p:.0f} > {choke_dp(r.delta_p):.0f} bar "
                 f"choke limit) — expect noise and erosion (CF8M is chosen for this)")
    return w


# ---------------------------------------------------------------------
# Interpretation (calibrate from a measured reading)
# ---------------------------------------------------------------------
def interpret(r: ValveResult, measured: dict | None = None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    msgs.append(("info",
        "The Cv and the equal-percentage shape are representative for a 1½″ globe "
        "valve, not a published curve. Enter a measured brine flow at a known "
        "hand-wheel position to calibrate the real characteristic."))
    if r.choked:
        msgs.append(("warn",
            "At this pressure drop the valve is cavitating — throttling the whole "
            "brine pressure across one valve. This limits the flow and erodes the "
            "trim over time; it is the main reason the body is CF8M stainless."))

    if not measured:
        return msgs

    op = measured.get("opening")
    dp = measured.get("delta_p")
    qm = measured.get("brine_flow")
    if op is not None and dp and qm:
        # implied Cv from the measurement vs the assumed Cv at that opening
        _, _, _, _, dp_eff = flow(op, dp, r.sg)
        cv_model = cv_at(op)
        cv_meas = qm / (KV_FACTOR * math.sqrt(max(dp_eff, 1e-6) / r.sg)) if dp_eff > 0 else 0.0
        if cv_model > 0:
            gap = (cv_meas - cv_model) / cv_model * 100.0
            if abs(gap) <= 10:
                msgs.append(("ok",
                    f"Measured flow implies Cv ≈ {cv_meas:.2f} at {op:.0f}% open, within "
                    f"{gap:+.0f}% of the assumed {cv_model:.2f} — the representative curve fits well."))
            else:
                msgs.append(("warn",
                    f"Measured flow implies Cv ≈ {cv_meas:.2f} at {op:.0f}% open, {gap:+.0f}% "
                    f"from the assumed {cv_model:.2f}. Collect a few more points and recalibrate "
                    f"Cv_max and the characteristic to your valve."))
    return msgs


# ---------------------------------------------------------------------
# Reference curves
# ---------------------------------------------------------------------
def flow_vs_opening(delta_p, sg=None, points=41):
    sg = v("SG") if sg is None else sg
    return [(op := 100.0 * i / (points - 1), flow(op, delta_p, sg)[0])
            for i in range(points)]


def flow_vs_dp(opening_pct, sg=None, lo=0.0, hi=80.0, points=41):
    sg = v("SG") if sg is None else sg
    out = []
    for i in range(points):
        dp = lo + (hi - lo) * i / (points - 1)
        out.append((dp, flow(opening_pct, dp, sg)[0]))
    return out
