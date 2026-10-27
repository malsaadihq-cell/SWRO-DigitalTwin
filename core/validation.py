"""Validation layer — three levels, every step shown on the page.

This module is rebuilt around a clear separation the examiner asked for.
Validation is layered: each level answers a different question, and a
model is only trusted after the level below it passes.

    Level 1 — DATA SELF-CONSISTENCY   (core/validation.py, this file)
        Do the RAW plant readings obey conservation on their own, with
        NO model and NO reference software? Pure mass/salt balance plus
        physical sanity. A reading set that fails here is wrong at the
        sensor, so nothing built on it can be trusted.

    Level 2 — MODEL vs PLANT
        Driven by the run's measured boundary conditions, does the
        single-element solution-diffusion model (IWA Ch. 9) reproduce
        what the plant measured, within tolerance? Measures the gap;
        adjusts NO parameter (that would be calibration, not validation).

    Level 3 — MODEL vs WAVE   (reference-software benchmark)
        Placeholder only — see the stub at the end. Not built yet, by
        request. The data model leaves a clean seat for it.

NOTHING here is read-for-write: no physics parameter (Kw, Ks, ΔPe, SR,
osmotic coefficient, Kp, pump rated flow, valve Cv …) is adjusted. Every
law is a named function; every result carries a `worked` LaTeX string
with the current numbers substituted, so the page can show the step, not
just the verdict.

Sensor set on the skid (unchanged from the previous build):
  - VFD frequency is set (constant 60 Hz across the campaign).
  - Feed flow is NOT measured → it IS the mass balance Qf = Qp + Qb,
    which is exactly why the raw-data mass-balance check uses the pump
    as the independent third number (Level 1 below).
  - Brine-valve opening is NOT measured → back-solved from the measured
    brine flow and brine pressure through the valve model.
  - Salinity is measured as conductivity (μS/cm) → TDS = EC × factor.
  - Four thermometers → isothermal check (feed T drives Kw, Ks).
  - Dual-port permeate conductivity → brine-side permeate should be
    saltier than feed-side (CH9 Fig. 10), the mixed outlet in between.
Ignored: cartridge-filter pressures, pH, duplicate analyser fields.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import math
from dataclasses import dataclass, field

from . import membrane, pump, valve

DEFAULT_EC_TO_TDS = 0.64   # seawater, mg/L per μS/cm

# Pressure is stored internally in bar everywhere in the model. The lab
# gauges read PSI, so pressure is converted ONCE at the point of entry
# (CSV load / page input) and never again — the rest of the program stays
# in bar and is untouched. 1 PSI = 0.0689476 bar.
PSI_TO_BAR = 0.0689476
PRESSURE_UNITS = {"bar": 1.0, "psi": PSI_TO_BAR}


def to_bar(value: float, unit: str = "bar") -> float:
    """Convert a pressure reading to bar. `unit` is 'bar' or 'psi'."""
    if value is None:
        return value
    try:
        return value * PRESSURE_UNITS[unit.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown pressure unit {unit!r}; use 'bar' or 'psi'")


# =====================================================================
# Acceptance bands
# =====================================================================
# Level 1 — closure thresholds for the raw-data balances, in % of the
# larger side. These are instrumentation-closure numbers, not model
# tolerances: a good flow/EC loop should close a balance to a few %.
DEFAULT_BALANCE_TOLERANCES: dict[str, float] = {
    "mass_balance": 5.0,     # Qf(pump) vs Qp + Qb
    "salt_balance": 5.0,     # salt in vs salt out
    "recovery": 2.0,         # Qp/Qf vs 1 − Qb/Qf  (absolute pp, see note)
}

# Level 2 — model-vs-plant bands, in % of the measured value.
DEFAULT_TOLERANCES: dict[str, float] = {
    "permeate_flow": 5.0,
    "permeate_tds": 15.0,
    "brine_tds": 10.0,
    "element_dp": 20.0,
    "feed_flow": 5.0,    # pump prediction vs mass balance
}

# key -> (label, display unit, LaTeX unit)
KPI_META: dict[str, tuple[str, str, str]] = {
    "permeate_flow": ("Permeate flow", "m³/h", r"\mathrm{m^3/h}"),
    "permeate_tds": ("Permeate TDS", "mg/L", r"\mathrm{mg/L}"),
    "brine_tds": ("Brine TDS", "mg/L", r"\mathrm{mg/L}"),
    "element_dp": ("Element ΔP", "bar", r"\mathrm{bar}"),
    "feed_flow": ("Feed flow", "m³/h", r"\mathrm{m^3/h}"),
}


def merged_tolerances(overrides: dict | None = None) -> dict[str, float]:
    tol = dict(DEFAULT_TOLERANCES)
    if overrides:
        tol.update({k: float(v) for k, v in overrides.items() if v is not None})
    return tol


def merged_balance_tolerances(overrides: dict | None = None) -> dict[str, float]:
    tol = dict(DEFAULT_BALANCE_TOLERANCES)
    if overrides:
        tol.update({k: float(v) for k, v in overrides.items() if v is not None})
    return tol


# =====================================================================
# Data model
# =====================================================================
@dataclass(frozen=True, kw_only=True)
class TestRun:
    """One steady-state operating point measured at the pilot plant.
    Field names reflect what the actual sensor list captures."""

    __test__ = False   # not a pytest test class

    run_id: str
    timestamp: str = ""
    notes: str = ""

    # Operator settings
    vfd_frequency_hz: float = 60.0

    # Pressures (bar) — sensors #3, #4
    hpp_feed_pressure: float
    hpp_brine_pressure: float

    # Conductivities (μS/cm) — sensors #5, #6, #7, #9, #10
    feed_conductivity: float
    brine_conductivity: float
    permeate_conductivity: float
    permeate_feed_side_conductivity: float | None = None
    permeate_brine_side_conductivity: float | None = None

    # Flows (m³/h) — sensors #11, #12
    permeate_flow: float
    brine_flow: float

    # Temperatures (°C) — four thermometers on the skid
    feed_temperature: float
    brine_temperature: float | None = None
    permeate_feed_side_temperature: float | None = None
    permeate_brine_side_temperature: float | None = None

    # EC → TDS conversion factor (seawater ≈ 0.64)
    ec_to_tds_factor: float = DEFAULT_EC_TO_TDS

    @property
    def feed_tds(self) -> float:
        return self.feed_conductivity * self.ec_to_tds_factor

    @property
    def brine_tds(self) -> float:
        return self.brine_conductivity * self.ec_to_tds_factor

    @property
    def permeate_tds(self) -> float:
        return self.permeate_conductivity * self.ec_to_tds_factor

    @property
    def feed_flow(self) -> float:
        return self.permeate_flow + self.brine_flow   # mass balance

    @property
    def element_dp_measured(self) -> float:
        return self.hpp_feed_pressure - self.hpp_brine_pressure

    @property
    def permeate_tds_gradient(self) -> float | None:
        if (self.permeate_feed_side_conductivity is None or
                self.permeate_brine_side_conductivity is None):
            return None
        f = self.permeate_feed_side_conductivity * self.ec_to_tds_factor
        b = self.permeate_brine_side_conductivity * self.ec_to_tds_factor
        return b - f


@dataclass
class BalanceCheck:
    """One raw-data conservation check (Level 1). `lhs`/`rhs` are the two
    sides that should be equal; closure is the residual as % of the
    larger side. No model is involved."""
    name: str
    label: str
    lhs: float
    rhs: float
    lhs_label: str
    rhs_label: str
    unit: str
    residual: float            # lhs − rhs  (signed)
    closure_pct: float         # 100·|lhs − rhs| / max(|lhs|, |rhs|)
    tolerance_pct: float
    closed: bool
    worked: str = ""


@dataclass
class SanityCheck:
    """One physical-plausibility check on the raw readings (Level 1).
    Pure inequality on measured numbers; no model, no balance."""
    name: str
    description: str
    ok: bool
    detail: str
    worked: str = ""


@dataclass
class DataConsistency:
    """Level 1 result for one run: the raw readings judged on their own."""
    run_id: str
    balances: list[BalanceCheck]
    sanity: list[SanityCheck]
    passed: bool               # every balance closed AND every sanity ok


@dataclass
class KpiComparison:
    """Level 2 primitive: one predicted vs measured KPI."""
    name: str
    unit: str
    predicted: float
    measured: float
    absolute_error: float          # |predicted − measured|
    relative_error_pct: float      # 100·(predicted − measured)/measured, signed
    within_tolerance: bool
    tolerance_pct: float
    worked: str = ""               # LaTeX line showing the comparison


@dataclass
class RunValidation:
    run: TestRun
    data_consistency: DataConsistency      # Level 1 (new)
    membrane_comparisons: list[KpiComparison]
    pump_comparisons: list[KpiComparison]
    mass_balance: dict
    valve_backsolve: dict
    thermal_consistency: dict
    permeate_gradient: dict
    overall_pass: bool                     # Level 1 AND Level 2 both pass

    @property
    def comparisons(self) -> list[KpiComparison]:
        return self.membrane_comparisons + self.pump_comparisons


@dataclass
class DatasetValidation:
    runs: list[RunValidation]
    metrics: dict[str, dict] = field(default_factory=dict)   # per KPI: n, bias, MAE, RMSE, MAPE


# =====================================================================
# Helpers
# =====================================================================
def conductivity_to_tds(ec: float, factor: float = DEFAULT_EC_TO_TDS) -> float:
    """TDS [mg/L] = EC [μS/cm] × factor (≈ 0.64 for seawater)."""
    return ec * factor


def _closure_pct(lhs: float, rhs: float) -> float:
    """Residual as % of the larger side (symmetric, 0 when both are 0)."""
    denom = max(abs(lhs), abs(rhs))
    return 100.0 * abs(lhs - rhs) / denom if denom else 0.0


# =====================================================================
# LEVEL 1 — DATA SELF-CONSISTENCY  (raw readings, no model)
# ---------------------------------------------------------------------
# These are the checks worked out on paper first: conservation laws the
# measurements must obey by themselves. They catch sensor/entry errors
# BEFORE any model runs. They prove the readings are self-consistent —
# NOT that they are free of a shared systematic error (a flow meter off
# by a constant factor can still close every balance). That limit is
# why Level 1 is necessary but not sufficient, and why Levels 2–3 exist.
# =====================================================================
def check_mass_balance(run: TestRun, tol_pct: float = 5.0,
                       pump_health: float = 1.0) -> BalanceCheck:
    """Overall mass balance on the raw flows.

        Qf = Qp + Qb

    Feed flow is not metered on this skid, so the independent third
    number is the pump's delivered flow at the set VFD frequency. The
    check is therefore: does the pump-side feed flow equal the sum of
    the two measured outlet flows?

        LHS  Qf,pump = Q_rated · n/1500 · health      (Danfoss p. 25)
        RHS  Qp + Qb                                   (measured)
    """
    rpm = pump.rpm_from_frequency(run.vfd_frequency_hz)
    q_pump = pump.nominal_flow(rpm) * pump_health
    q_out = run.permeate_flow + run.brine_flow
    res = q_pump - q_out
    clo = _closure_pct(q_pump, q_out)
    mark = r"\checkmark" if clo <= tol_pct else r"\times"
    worked = (rf"Q_{{f,\text{{pump}}}} = Q_p + Q_b:\quad {q_pump:.2f} \;?=\; "
              rf"{run.permeate_flow:.2f} + {run.brine_flow:.2f} = {q_out:.2f}\ \mathrm{{m^3/h}}"
              rf"\quad\Rightarrow\ \text{{closure}} = \frac{{|{res:+.2f}|}}{{{max(abs(q_pump), abs(q_out)):.2f}}}"
              rf" = {clo:.1f}\%\ (\le {tol_pct:g}\%\ {mark})")
    return BalanceCheck(
        name="mass_balance", label="Overall mass balance (Qf = Qp + Qb)",
        lhs=q_pump, rhs=q_out, lhs_label="Qf (pump)", rhs_label="Qp + Qb",
        unit="m³/h", residual=res, closure_pct=clo, tolerance_pct=tol_pct,
        closed=clo <= tol_pct, worked=worked)


def check_salt_balance(run: TestRun, tol_pct: float = 5.0,
                       pump_health: float = 1.0) -> BalanceCheck:
    """Salt (solute) balance on the raw readings.

        Qf·Cf = Qp·Cp + Qb·Cb

    Salt carried in by the feed must leave in the permeate plus the
    brine. Flows in m³/h, TDS in mg/L (from EC × factor); each product
    is a salt-mass rate in g/h. Feed flow again comes from the pump so
    the left side does not reuse Qp + Qb.
    """
    rpm = pump.rpm_from_frequency(run.vfd_frequency_hz)
    qf = pump.nominal_flow(rpm) * pump_health
    cf, cp, cb = run.feed_tds, run.permeate_tds, run.brine_tds
    salt_in = qf * cf
    salt_out = run.permeate_flow * cp + run.brine_flow * cb
    res = salt_in - salt_out
    clo = _closure_pct(salt_in, salt_out)
    mark = r"\checkmark" if clo <= tol_pct else r"\times"
    worked = (rf"Q_f C_f = Q_p C_p + Q_b C_b:\quad "
              rf"{qf:.2f}\times{cf:.0f} \;?=\; {run.permeate_flow:.2f}\times{cp:.0f}"
              rf" + {run.brine_flow:.2f}\times{cb:.0f}"
              rf"\quad\Rightarrow\ {salt_in:,.0f} \;?=\; {salt_out:,.0f}\ \mathrm{{g/h}}"
              rf"\quad(\text{{closure}} = {clo:.1f}\%\ \le {tol_pct:g}\%\ {mark})")
    return BalanceCheck(
        name="salt_balance", label="Salt balance (Qf·Cf = Qp·Cp + Qb·Cb)",
        lhs=salt_in, rhs=salt_out, lhs_label="Qf·Cf", rhs_label="Qp·Cp + Qb·Cb",
        unit="g/h", residual=res, closure_pct=clo, tolerance_pct=tol_pct,
        closed=clo <= tol_pct, worked=worked)


def check_recovery_consistency(run: TestRun, tol_pp: float = 2.0) -> BalanceCheck:
    """Recovery computed two ways from the measured flows must agree.

        R = Qp/Qf          and          R = 1 − Qb/Qf

    Here Qf = Qp + Qb (the balance definition), so the two are algebraically
    identical and the residual is numerically ~0 by construction. It is kept
    as an explicit, visible check because the examiner listed it, and because
    it documents that recovery is read off the flows, not assumed. Closure is
    reported in percentage POINTS of recovery, not relative %.
    """
    qf = run.feed_flow
    r_direct = (run.permeate_flow / qf) if qf else math.nan
    r_comp = (1.0 - run.brine_flow / qf) if qf else math.nan
    res_pp = (r_direct - r_comp) * 100.0
    clo_pp = abs(res_pp)
    mark = r"\checkmark" if clo_pp <= tol_pp else r"\times"
    worked = (rf"R = \frac{{Q_p}}{{Q_f}} = \frac{{{run.permeate_flow:.2f}}}{{{qf:.2f}}}"
              rf" = {r_direct*100:.1f}\%\quad\text{{vs}}\quad "
              rf"1 - \frac{{Q_b}}{{Q_f}} = 1 - \frac{{{run.brine_flow:.2f}}}{{{qf:.2f}}}"
              rf" = {r_comp*100:.1f}\%\quad(\Delta = {res_pp:+.2f}\ \text{{pp}}"
              rf"\ \le {tol_pp:g}\ \text{{pp}}\ {mark})")
    return BalanceCheck(
        name="recovery", label="Recovery consistency (Qp/Qf = 1 − Qb/Qf)",
        lhs=r_direct * 100.0, rhs=r_comp * 100.0, lhs_label="Qp/Qf",
        rhs_label="1 − Qb/Qf", unit="%", residual=res_pp, closure_pct=clo_pp,
        tolerance_pct=tol_pp, closed=clo_pp <= tol_pp, worked=worked)


def sanity_checks(run: TestRun) -> list[SanityCheck]:
    """Physical-plausibility inequalities on the raw readings. Each is a
    hard yes/no on measured numbers: a failure means a reading is
    impossible, independent of any balance closing."""
    out: list[SanityCheck] = []
    qf = run.feed_flow
    cf, cp, cb = run.feed_tds, run.permeate_tds, run.brine_tds

    # 1. outlet flows below the feed
    ok = run.permeate_flow < qf and run.brine_flow < qf
    out.append(SanityCheck(
        "outlets_below_feed", "Each outlet flow is below the feed flow",
        ok, f"Qp = {run.permeate_flow:.2f}, Qb = {run.brine_flow:.2f}, Qf = {qf:.2f} m³/h",
        rf"Q_p,\,Q_b < Q_f:\ {run.permeate_flow:.2f},\,{run.brine_flow:.2f} < {qf:.2f}"))

    # 2. salinity ordering: permeate < feed < brine
    ok = cp < cf < cb
    out.append(SanityCheck(
        "salinity_ordering", "Salinity ordering Cp < Cf < Cb",
        ok, f"Cp = {cp:.0f}, Cf = {cf:.0f}, Cb = {cb:.0f} mg/L",
        rf"C_p < C_f < C_b:\ {cp:.0f} < {cf:.0f} < {cb:.0f}\ \mathrm{{mg/L}}"))

    # 3. brine pressure below feed pressure (ΔP across the element is positive)
    dp = run.element_dp_measured
    ok = dp > 0
    out.append(SanityCheck(
        "positive_element_dp", "Feed pressure above brine pressure (ΔP > 0)",
        ok, f"ΔP = {dp:+.2f} bar (feed {run.hpp_feed_pressure:.1f}, brine {run.hpp_brine_pressure:.1f})",
        rf"P_{{feed}} > P_{{brine}}:\ {run.hpp_feed_pressure:.1f} > {run.hpp_brine_pressure:.1f}\ \mathrm{{bar}}"))

    return out


def check_data_consistency(run: TestRun, balance_tol: dict | None = None,
                           pump_health: float = 1.0) -> DataConsistency:
    """Level 1 for one run: raw readings judged on their own, no model.
    `passed` requires every balance to close AND every sanity check ok."""
    bt = merged_balance_tolerances(balance_tol)
    balances = [
        check_mass_balance(run, bt["mass_balance"], pump_health),
        check_salt_balance(run, bt["salt_balance"], pump_health),
        check_recovery_consistency(run, bt["recovery"]),
    ]
    sanity = sanity_checks(run)
    passed = all(b.closed for b in balances) and all(s.ok for s in sanity)
    return DataConsistency(run_id=run.run_id, balances=balances, sanity=sanity,
                           passed=passed)


# =====================================================================
# LEVEL 2 — MODEL vs PLANT
# ---------------------------------------------------------------------
# Comparison primitive, the per-block drivers, the back-solves and
# cross-checks that support them, and the dataset aggregates.
# =====================================================================
def compare_kpi(name: str, predicted: float, measured: float,
                tolerance_pct: float) -> KpiComparison:
    """One KPI: Δ = predicted − measured,  rel = 100·Δ/measured,
    pass when |rel| ≤ tolerance."""
    label, unit, tex_unit = KPI_META.get(name, (name, "", ""))
    delta = predicted - measured
    if measured != 0:
        rel = 100.0 * delta / abs(measured)
        ok = abs(rel) <= tolerance_pct
    else:
        rel = math.nan
        ok = delta == 0
    mark = r"\checkmark" if ok else r"\times"
    rel_tex = "n/a" if math.isnan(rel) else f"{rel:+.1f}\\%"
    worked = (rf"\text{{{label}}}:\ \hat y = {predicted:.4g},\ y = {measured:.4g},\ "
              rf"\Delta = \hat y - y = {delta:+.3g}\ {tex_unit}\ ({rel_tex};\ "
              rf"|\cdot|\le {tolerance_pct:g}\%\ {mark})")
    return KpiComparison(name=name, unit=unit, predicted=predicted, measured=measured,
                         absolute_error=abs(delta), relative_error_pct=rel,
                         within_tolerance=ok, tolerance_pct=tolerance_pct, worked=worked)


def backsolve_valve_opening(brine_flow: float, brine_pressure: float,
                            SG: float = 1.03) -> dict:
    """Back-solve the (unmeasured) brine-valve opening.

    The brine discharges to ~atmospheric, so the measured brine-outlet
    pressure equals the valve ΔP. Bisect the opening in [1, 100] % on the
    valve model, ΔP(x) = (Qb / (0.865·Cv(x)))²·SG, which falls
    monotonically as the valve opens. Converged when the achieved ΔP is
    within 0.1 bar of the target.
    """
    def dp(x):
        return valve.simulate(x, brine_flow, sg=SG).delta_p

    lo, hi = 1.0, 100.0
    if brine_pressure >= dp(lo):
        x = lo
    elif brine_pressure <= dp(hi):
        x = hi
    else:
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if dp(mid) > brine_pressure:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-9:
                break
        x = 0.5 * (lo + hi)

    vr = valve.simulate(x, brine_flow, sg=SG)
    achieved = vr.delta_p
    converged = math.isfinite(achieved) and abs(achieved - brine_pressure) <= 0.1
    worked = (rf"\text{{solve }}x:\ \left(\frac{{Q_b}}{{0.865\,C_v(x)}}\right)^2 SG = P_{{brine}}"
              rf"\ \Rightarrow\ \left(\frac{{{brine_flow:.2f}}}{{0.865\times {vr.cv:.3f}}}\right)^2"
              rf"\times {SG:.2f} = {achieved:.2f}\ \mathrm{{bar}}\ (\text{{target }}{brine_pressure:.2f})"
              rf"\ \Rightarrow\ x = {x:.1f}\%")
    return dict(opening_pct=x, achieved_dp_bar=achieved, target_dp_bar=brine_pressure,
                cv=vr.cv, cavitating=vr.cavitating, converged=converged, worked=worked)


def mass_balance_check(run: TestRun, pump_health: float = 1.0) -> dict:
    """Pump-predicted feed flow vs the mass-balance feed flow (the same
    numbers as Level-1 check_mass_balance, kept in dict form for the
    page's metric widgets and the Markdown report):

        Qf_pump = Q_rated · (f·30)/1500 · h       (Danfoss p. 25)
        Qf_bal  = Qp + Qb
        gap_pct = 100·(Qf_pump − Qf_bal)/Qf_bal
    """
    rpm = pump.rpm_from_frequency(run.vfd_frequency_hz)
    q_pump = pump.nominal_flow(rpm) * pump_health
    q_bal = run.feed_flow
    gap = 100.0 * (q_pump - q_bal) / q_bal if q_bal else math.nan
    worked = (rf"Q_{{f,pump}} = Q_{{rated}}\frac{{n}}{{1500}}h = {pump.v('rated_flow')}"
              rf"\times\frac{{{rpm:.0f}}}{{1500}}\times {pump_health:.2f} = {q_pump:.2f};\quad "
              rf"Q_{{f,bal}} = Q_p + Q_b = {run.permeate_flow:.2f} + {run.brine_flow:.2f}"
              rf" = {q_bal:.2f};\quad \text{{gap}} = {gap:+.1f}\%")
    return dict(qfeed_pump=q_pump, qfeed_balance=q_bal, gap_pct=gap, rpm=rpm,
                pump_warnings=pump._check_limits(rpm, run.hpp_feed_pressure, pump.v("inlet_min")),
                worked=worked)


def thermal_consistency(run: TestRun, tol_C: float = 1.0) -> dict:
    """max |T_other − T_feed| over the diagnostic thermometers present;
    isothermal = max_delta ≤ tol_C. The feed temperature is the one the
    model uses for Kw(T), Ks(T)."""
    others = {
        "brine": run.brine_temperature,
        "permeate (feed side)": run.permeate_feed_side_temperature,
        "permeate (brine side)": run.permeate_brine_side_temperature,
    }
    others = {k: t for k, t in others.items() if t is not None}
    deltas = {k: abs(t - run.feed_temperature) for k, t in others.items()}
    max_delta = max(deltas.values()) if deltas else 0.0
    isothermal = max_delta <= tol_C
    rel = r"\le" if isothermal else ">"
    worked = (rf"\max_i |T_i - T_{{feed}}| = {max_delta:.2f}\ ^\circ\mathrm{{C}}"
              rf"\ {rel}\ {tol_C:.1f}\ ^\circ\mathrm{{C}}"
              rf"\quad({len(others)}\ \text{{thermometers vs }} T_{{feed}} = {run.feed_temperature:.1f})")
    return dict(max_delta_C=max_delta, isothermal=isothermal, reference=run.feed_temperature,
                n_other=len(others), deltas=deltas, tol_C=tol_C, worked=worked)


def permeate_gradient_check(run: TestRun) -> dict:
    """Dual-port permeate check (CH9 Fig. 10): the permeate collected near
    the brine end is saltier than near the feed end, and the mixed outlet
    sits between them.

        direction_ok  = brine-side TDS > feed-side TDS
        mixed_between = min(f, b) ≤ mixed ≤ max(f, b)
    """
    if (run.permeate_feed_side_conductivity is None or
            run.permeate_brine_side_conductivity is None):
        return dict(available=False)
    k = run.ec_to_tds_factor
    f = run.permeate_feed_side_conductivity * k
    b = run.permeate_brine_side_conductivity * k
    mixed = run.permeate_tds
    direction_ok = b > f
    between = min(f, b) <= mixed <= max(f, b)
    rel = r"\le" if between else r"\not\le"
    worked = (rf"C_{{p,\text{{brine side}}}} - C_{{p,\text{{feed side}}}} = {b:.1f} - {f:.1f}"
              rf" = {b - f:+.1f}\ \mathrm{{mg/L}};\quad "
              rf"{min(f, b):.1f} {rel} C_{{p,\text{{mixed}}}} = {mixed:.1f}"
              rf" {rel} {max(f, b):.1f}")
    return dict(available=True, feed_side_tds=f, mixed_tds=mixed, brine_side_tds=b,
                gradient_mgL=b - f, direction_ok=direction_ok,
                mixed_between_ports=between, worked=worked)


def membrane_boundary(run: TestRun, fouling: float = 1.0) -> membrane.MembraneResult:
    """Run the membrane model at the test run's measured boundary conditions."""
    return membrane.simulate(
        feed_pressure=run.hpp_feed_pressure,
        feed_tds=run.feed_tds,
        temperature=run.feed_temperature,
        feed_flow=run.feed_flow,
        fouling=fouling,
    )


def validate_membrane_block(run: TestRun, tolerances: dict | None = None,
                            fouling: float = 1.0) -> list[KpiComparison]:
    """Drive membrane.simulate with the run's measured boundary conditions
    (feed pressure, feed TDS, feed temperature, Qf = Qp + Qb) and compare
    permeate_flow, permeate_tds, brine_tds and element_dp."""
    r = membrane_boundary(run, fouling)
    measured = {
        "permeate_flow": run.permeate_flow,
        "permeate_tds": run.permeate_tds,
        "brine_tds": run.brine_tds,
        "element_dp": run.element_dp_measured,
    }
    return membrane.validate_membrane(r, measured, tolerances)


def validate_pump_block(run: TestRun, tolerances: dict | None = None,
                        health: float = 1.0) -> list[KpiComparison]:
    """At the set VFD frequency the PD pump should deliver a known feed
    flow; compare Q_rated·n/1500·h against the mass-balance Qp + Qb."""
    tol = merged_tolerances(tolerances)
    q_pump = pump.nominal_flow(pump.rpm_from_frequency(run.vfd_frequency_hz)) * health
    return [compare_kpi("feed_flow", q_pump, run.feed_flow, tol["feed_flow"])]


# =====================================================================
# Drivers — one run, whole dataset
# =====================================================================
def validate_run(run: TestRun, tolerances: dict | None = None, health: float = 1.0,
                 fouling: float = 1.0, balance_tol: dict | None = None) -> RunValidation:
    """Full validation of one run.

    Level 1 (data self-consistency) runs first; Level 2 (model vs plant)
    runs regardless so the page can show both, but overall_pass requires
    BOTH: the raw data must be self-consistent AND the model must match
    it within tolerance. A model 'matching' inconsistent data is not a
    pass — that is the whole point of layering.
    """
    dc = check_data_consistency(run, balance_tol, health)
    mc = validate_membrane_block(run, tolerances, fouling)
    pc = validate_pump_block(run, tolerances, health)
    model_ok = all(c.within_tolerance for c in mc + pc)
    return RunValidation(
        run=run,
        data_consistency=dc,
        membrane_comparisons=mc,
        pump_comparisons=pc,
        mass_balance=mass_balance_check(run, health),
        valve_backsolve=backsolve_valve_opening(run.brine_flow, run.hpp_brine_pressure,
                                                 valve.v("SG")),
        thermal_consistency=thermal_consistency(run),
        permeate_gradient=permeate_gradient_check(run),
        overall_pass=dc.passed and model_ok,
    )


def aggregate_metrics(comparisons: list[KpiComparison]) -> dict[str, dict]:
    """Per-KPI aggregates (e = predicted − measured):
        n = count, bias = mean(e), MAE = mean|e|, RMSE = sqrt(mean e²),
        MAPE = mean(|e|/|measured|)·100  (points with measured = 0 skipped)."""
    by_kpi: dict[str, list[KpiComparison]] = {}
    for c in comparisons:
        if c.measured is None or c.predicted is None:
            continue
        by_kpi.setdefault(c.name, []).append(c)
    out = {}
    for name, cs in by_kpi.items():
        e = [c.predicted - c.measured for c in cs]
        ape = [abs(c.predicted - c.measured) / abs(c.measured) * 100.0
               for c in cs if c.measured != 0]
        n = len(e)
        out[name] = dict(
            n=n,
            unit=cs[0].unit,
            bias=sum(e) / n,
            MAE=sum(abs(x) for x in e) / n,
            RMSE=math.sqrt(sum(x * x for x in e) / n),
            MAPE=(sum(ape) / len(ape)) if ape else math.nan,
        )
    return out


def validate_dataset(runs: list[TestRun], tolerances: dict | None = None,
                     health: float = 1.0, fouling: float = 1.0,
                     balance_tol: dict | None = None) -> DatasetValidation:
    """Validate every run, then aggregate per KPI across runs."""
    rvs = [validate_run(r, tolerances, health, fouling, balance_tol) for r in runs]
    return DatasetValidation(
        runs=rvs,
        metrics=aggregate_metrics([c for rv in rvs for c in rv.comparisons]),
    )


# =====================================================================
# Diagnosis of a failed KPI (direction = measured relative to predicted)
# =====================================================================
def diagnose(c: KpiComparison) -> str:
    low = c.measured < c.predicted
    label = KPI_META.get(c.name, (c.name,))[0]
    word = "low" if low else "high"
    if c.name == "permeate_flow":
        cause = ("fouling, scaling, or Kw lower than catalogue" if low else
                 "flow-meter calibration or Kw higher than catalogue")
    elif c.name == "permeate_tds":
        cause = ("Ks higher than catalogue, membrane ageing, seal leak" if not low else
                 "salt passage below catalogue — check the permeate EC probe and the "
                 "EC→TDS factor (0.64 is a seawater factor)")
    elif c.name == "element_dp":
        cause = ("spacer fouling" if not low else
                 "below the assumed 0.2 bar head loss — check gauge resolution at this pressure")
    elif c.name == "feed_flow":
        cause = "pump health < 1 or flow-meter calibration"
    elif c.name == "brine_tds":
        cause = "check the brine EC probe and the EC→TDS factor"
    else:
        cause = "outside tolerance"
    return f"{label} {word} ({c.relative_error_pct:+.1f}% model vs plant) → {cause}"


def diagnose_balance(b: BalanceCheck) -> str:
    """Plain-language reading of a failed Level-1 balance."""
    if b.name == "mass_balance":
        who = "pump flow is above the metered outlets" if b.residual > 0 else \
              "metered outlets exceed the pump flow"
        return (f"Mass balance open by {b.closure_pct:.1f}% ({who}) → a flow meter "
                f"(permeate or brine) or the pump health factor is off.")
    if b.name == "salt_balance":
        who = "salt in exceeds salt out" if b.residual > 0 else "salt out exceeds salt in"
        return (f"Salt balance open by {b.closure_pct:.1f}% ({who}) → an EC probe or the "
                f"EC→TDS factor is off, or a flow reading is wrong.")
    if b.name == "recovery":
        return (f"Recovery mismatch {b.closure_pct:.1f} pp — unexpected, since the two "
                f"forms are algebraically equal; check for a data-entry anomaly.")
    return f"{b.label} open by {b.closure_pct:.1f}%"


# =====================================================================
# I/O
# =====================================================================
_STR_FIELDS = {"run_id", "timestamp", "notes"}


_PRESSURE_FIELDS = {"hpp_feed_pressure", "hpp_brine_pressure"}


def load_runs_csv(path, pressure_unit: str = "bar") -> list[TestRun]:
    """CSV columns match TestRun field names; unknown columns are ignored.
    Blank → None (fields with a numeric default fall back to that default).
    `path` may be a filesystem path or a file-like object (e.g. an upload).

    `pressure_unit` is the unit of the pressure columns in the file ('bar'
    or 'psi'). If 'psi', the two pressure columns are converted to bar on
    load, so every TestRun is stored in bar regardless of how it was
    recorded — the lab records PSI, the model works in bar."""
    if hasattr(path, "read"):
        raw = path.read()
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
    fields = {f.name: f for f in dataclasses.fields(TestRun)}
    runs = []
    for row in csv.DictReader(io.StringIO(text)):
        kwargs = {}
        for k, raw_v in row.items():
            if k is None or k.strip() not in fields:
                continue
            k = k.strip()
            s = (raw_v or "").strip()
            if k in _STR_FIELDS:
                kwargs[k] = s
            elif s == "":
                if fields[k].default is dataclasses.MISSING or fields[k].default is None:
                    kwargs[k] = None
            else:
                val = float(s)
                if k in _PRESSURE_FIELDS:
                    val = to_bar(val, pressure_unit)
                kwargs[k] = val
        runs.append(TestRun(**kwargs))
    return runs


def _fmt(x, nd=3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}g}" if abs(x) >= 1000 else f"{x:.{nd}f}"


def report_md(ds: DatasetValidation) -> str:
    """Markdown report: Level-1 data consistency + Level-2 per-run table +
    aggregate metrics + verdict."""
    n_pass = sum(rv.overall_pass for rv in ds.runs)
    n_data_ok = sum(rv.data_consistency.passed for rv in ds.runs)
    lines = [
        "# SWRO digital twin — validation report",
        "",
        "Parameters are kept exactly as sourced (Hydranautics ESS, Danfoss manual, "
        "IWA 2021 Ch. 9). Validation is layered: Level 1 tests the raw readings "
        "against conservation laws with no model; Level 2 tests the model against "
        "those readings. No parameter was adjusted.",
        "",
        f"**Verdict:** {n_data_ok} of {len(ds.runs)} runs are self-consistent (Level 1); "
        f"{n_pass} of {len(ds.runs)} also pass model-vs-plant (Level 2).",
        "",
    ]
    for rv in ds.runs:
        r = rv.run
        dc = rv.data_consistency
        lines += [
            f"## Run {r.run_id} — {'PASS' if rv.overall_pass else 'FAIL'}",
            "",
            f"{r.timestamp}  {r.notes}".strip(),
            "",
            "### Level 1 — data self-consistency (raw readings, no model)",
            "",
            f"Data consistency: {'OK' if dc.passed else 'CHECK'}",
            "",
            "| Balance | LHS | RHS | Closure % | Tol % | OK |",
            "|---|---|---|---|---|---|",
        ]
        for b in dc.balances:
            lines.append(f"| {b.label} | {b.lhs:.4g} | {b.rhs:.4g} | {b.closure_pct:.1f} | "
                         f"{b.tolerance_pct:g} | {'✓' if b.closed else '✗'} |")
        lines += ["", "| Sanity check | Result | OK |", "|---|---|---|"]
        for s in dc.sanity:
            lines.append(f"| {s.description} | {s.detail} | {'✓' if s.ok else '✗'} |")
        for b in dc.balances:
            if not b.closed:
                lines.append(f"- Diagnosis: {diagnose_balance(b)}")
        lines += [
            "",
            "### Level 2 — model vs plant",
            "",
            "| KPI | Predicted | Measured | Abs err | Rel err % | Tol % | OK |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in rv.comparisons:
            label, unit, _ = KPI_META.get(c.name, (c.name, c.unit, ""))
            lines.append(f"| {label} ({unit}) | {c.predicted:.4g} | {c.measured:.4g} | "
                         f"{c.absolute_error:.3g} | {c.relative_error_pct:+.1f} | "
                         f"{c.tolerance_pct:g} | {'✓' if c.within_tolerance else '✗'} |")
        mb, vb, th, pg = rv.mass_balance, rv.valve_backsolve, rv.thermal_consistency, rv.permeate_gradient
        lines += [
            "",
            f"- Valve back-solve: opening ≈ {vb['opening_pct']:.1f} % "
            f"(ΔP {vb['achieved_dp_bar']:.2f} vs {vb['target_dp_bar']:.2f} bar, "
            f"{'converged' if vb['converged'] else 'NOT converged'})",
            f"- Thermal: max |ΔT| = {th['max_delta_C']:.2f} °C over {th['n_other']} "
            f"thermometers — {'isothermal' if th['isothermal'] else 'NOT isothermal'}",
        ]
        if pg.get("available"):
            ok = pg["direction_ok"] and pg["mixed_between_ports"]
            lines.append(f"- Permeate gradient: feed side {pg['feed_side_tds']:.1f}, mixed "
                         f"{pg['mixed_tds']:.1f}, brine side {pg['brine_side_tds']:.1f} mg/L "
                         f"— {'consistent' if ok else 'INCONSISTENT'}")
        for c in rv.comparisons:
            if not c.within_tolerance:
                lines.append(f"- Diagnosis: {diagnose(c)}")
        lines.append("")
    lines += [
        "## Dataset metrics (e = predicted − measured)",
        "",
        "| KPI | n | bias | MAE | RMSE | MAPE % |",
        "|---|---|---|---|---|---|",
    ]
    for name, mt in ds.metrics.items():
        label, unit, _ = KPI_META.get(name, (name, mt["unit"], ""))
        lines.append(f"| {label} ({unit}) | {mt['n']} | {_fmt(mt['bias'])} | {_fmt(mt['MAE'])} | "
                     f"{_fmt(mt['RMSE'])} | {_fmt(mt['MAPE'], 2)} |")
    return "\n".join(lines) + "\n"


def save_report_md(ds: DatasetValidation, path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report_md(ds))


# =====================================================================
# LEVEL 3 — MODEL vs WAVE  (reference-software benchmark) — STUB
# ---------------------------------------------------------------------
# Not built yet, by request. When added, it will reuse compare_kpi and
# KpiComparison unchanged: feed the same boundary conditions to the
# model and to a WAVE run, then compare Qp, Cp, R, feed pressure, Cb.
# Deviation is taken relative to WAVE (the industry reference), the same
# shape as Level 2, so no new primitive is needed — only a WaveRun input
# and a validate_wave_block(run, wave_run) driver.
# =====================================================================
