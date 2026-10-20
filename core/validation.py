"""Validation layer — model vs pilot-plant measurements.

This module measures the gap between the digital twin's predictions and
what the plant's sensors record. It is validation, NOT calibration: no
physics parameter (Kw, Ks, ΔPe, SR, osmotic coefficient, Kp, the pump
rated flow, the valve Cv …) is read-for-write or adjusted here.

Tailored to the actual sensor set on the skid:
  - VFD frequency is set (constant 60 Hz across the campaign).
  - Feed flow is NOT measured → mass balance  Qf = Qp + Qb.
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

# Default acceptance bands, in % of the measured value (overridable per call)
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


# ---------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------
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
class KpiComparison:
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
    membrane_comparisons: list[KpiComparison]
    pump_comparisons: list[KpiComparison]
    mass_balance: dict
    valve_backsolve: dict
    thermal_consistency: dict
    permeate_gradient: dict
    overall_pass: bool

    @property
    def comparisons(self) -> list[KpiComparison]:
        return self.membrane_comparisons + self.pump_comparisons


@dataclass
class DatasetValidation:
    runs: list[RunValidation]
    metrics: dict[str, dict] = field(default_factory=dict)   # per KPI: n, bias, MAE, RMSE, MAPE


# ---------------------------------------------------------------------
# Comparison primitive
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def conductivity_to_tds(ec: float, factor: float = DEFAULT_EC_TO_TDS) -> float:
    """TDS [mg/L] = EC [μS/cm] × factor (≈ 0.64 for seawater)."""
    return ec * factor


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
    """Pump-predicted feed flow vs the mass-balance feed flow:

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


# ---------------------------------------------------------------------
# Validation drivers
# ---------------------------------------------------------------------
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


def validate_run(run: TestRun, tolerances: dict | None = None, health: float = 1.0,
                 fouling: float = 1.0) -> RunValidation:
    """Membrane + pump comparisons, mass balance, valve back-solve, thermal
    consistency and permeate gradient for one run. overall_pass requires
    every KPI comparison (membrane and pump) to be within tolerance."""
    mc = validate_membrane_block(run, tolerances, fouling)
    pc = validate_pump_block(run, tolerances, health)
    return RunValidation(
        run=run,
        membrane_comparisons=mc,
        pump_comparisons=pc,
        mass_balance=mass_balance_check(run, health),
        valve_backsolve=backsolve_valve_opening(run.brine_flow, run.hpp_brine_pressure,
                                                valve.v("SG")),
        thermal_consistency=thermal_consistency(run),
        permeate_gradient=permeate_gradient_check(run),
        overall_pass=all(c.within_tolerance for c in mc + pc),
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
                     health: float = 1.0, fouling: float = 1.0) -> DatasetValidation:
    """Validate every run, then aggregate per KPI across runs."""
    rvs = [validate_run(r, tolerances, health, fouling) for r in runs]
    return DatasetValidation(
        runs=rvs,
        metrics=aggregate_metrics([c for rv in rvs for c in rv.comparisons]),
    )


# ---------------------------------------------------------------------
# Diagnosis of a failed KPI (direction = measured relative to predicted)
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------
_STR_FIELDS = {"run_id", "timestamp", "notes"}


def load_runs_csv(path) -> list[TestRun]:
    """CSV columns match TestRun field names; unknown columns are ignored.
    Blank → None (fields with a numeric default fall back to that default).
    `path` may be a filesystem path or a file-like object (e.g. an upload)."""
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
                kwargs[k] = float(s)
        runs.append(TestRun(**kwargs))
    return runs


def _fmt(x, nd=3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}g}" if abs(x) >= 1000 else f"{x:.{nd}f}"


def report_md(ds: DatasetValidation) -> str:
    """Markdown report: per-run table + aggregate metrics + verdict."""
    n_pass = sum(rv.overall_pass for rv in ds.runs)
    lines = [
        "# SWRO digital twin — validation report",
        "",
        "Parameters are kept exactly as sourced (Hydranautics ESS, Danfoss manual, "
        "IWA 2021 Ch. 9). This report measures the model–plant gap; no parameter "
        "was adjusted.",
        "",
        f"**Verdict:** {n_pass} of {len(ds.runs)} runs within tolerance on every KPI.",
        "",
    ]
    for rv in ds.runs:
        r = rv.run
        lines += [
            f"## Run {r.run_id} — {'PASS' if rv.overall_pass else 'FAIL'}",
            "",
            f"{r.timestamp}  {r.notes}".strip(),
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
            f"- Mass balance: Qf(pump) = {mb['qfeed_pump']:.2f} m³/h at {mb['rpm']:.0f} rpm, "
            f"Qp + Qb = {mb['qfeed_balance']:.2f} m³/h, gap {mb['gap_pct']:+.1f} %",
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
