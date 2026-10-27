"""Validation view — model vs plant.

Takes steady-state test runs recorded at the pilot plant (manual entry or
CSV), drives each block with the run's measured boundary conditions and
reports the gap per KPI, per run and across the dataset. Nothing here
adjusts a physics parameter — see core/validation.py.
"""
from __future__ import annotations

import dataclasses
import math

import altair as alt
import pandas as pd
import streamlit as st

from core import validation as V

LINE = "#285A7A"      # steel blue — 45° reference line / band
INK = "#201E1A"
GRID = "#D7D1C4"
# validated categorical order (dataviz reference palette, light mode), fixed — never cycled
RUN_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
OTHER = "#8a8a85"

CAPTION = (
    "Parameters are kept exactly as sourced from the Hydranautics ESS, the Danfoss "
    "pump manual, and IWA Ch. 9. This page measures the gap between the model's "
    "predictions and the plant's measurements; it does not adjust any parameter. VFD "
    "was held at 60 Hz across the test campaign; the valve opening is back-solved from "
    "the measured brine flow and brine pressure."
)

# (field, column label, group) — order is the editor's column order
COLUMNS = [
    ("run_id", "Run ID", "Run"),
    ("timestamp", "Timestamp", "Run"),
    ("notes", "Notes", "Run"),
    ("vfd_frequency_hz", "Operator · VFD (Hz)", "Operator"),
    ("hpp_feed_pressure", "Pressures · feed #3 (bar)", "Pressures"),
    ("hpp_brine_pressure", "Pressures · brine #4 (bar)", "Pressures"),
    ("feed_conductivity", "Conductivities · feed #5 (μS/cm)", "Conductivities"),
    ("brine_conductivity", "Conductivities · brine #6 (μS/cm)", "Conductivities"),
    ("permeate_conductivity", "Conductivities · permeate mixed #7 (μS/cm)", "Conductivities"),
    ("permeate_feed_side_conductivity", "Conductivities · permeate feed side #9 (μS/cm)", "Conductivities"),
    ("permeate_brine_side_conductivity", "Conductivities · permeate brine side #10 (μS/cm)", "Conductivities"),
    ("permeate_flow", "Flows · permeate #11 (m³/h)", "Flows"),
    ("brine_flow", "Flows · brine #12 (m³/h)", "Flows"),
    ("feed_temperature", "Temperatures · feed (°C)", "Temperatures"),
    ("brine_temperature", "Temperatures · brine (°C)", "Temperatures"),
    ("permeate_feed_side_temperature", "Temperatures · permeate feed side (°C)", "Temperatures"),
    ("permeate_brine_side_temperature", "Temperatures · permeate brine side (°C)", "Temperatures"),
]
STR_FIELDS = {"run_id", "timestamp", "notes"}
REQUIRED = [f.name for f in dataclasses.fields(V.TestRun)
            if f.default is dataclasses.MISSING]

PARITY_KPIS = ["permeate_flow", "permeate_tds", "element_dp"]


def _empty_runs() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="string" if c in STR_FIELDS else "float")
                       for c, _, _ in COLUMNS})
    return df


def _example_run() -> pd.DataFrame:
    """The model-generated perfect-match run used in tests/test_validation.py."""
    from core import membrane, system
    k, P, Cf, T, hz = V.DEFAULT_EC_TO_TDS, 60.0, 41_000.0, 25.0, 60.0
    qf = system.feed_flow(hz)
    r = membrane.simulate(P, Cf, T, qf)
    row = dict(
        run_id="EXAMPLE-model", timestamp="", notes="model-generated, not plant data",
        vfd_frequency_hz=hz, hpp_feed_pressure=P, hpp_brine_pressure=P - r.element_dp,
        feed_conductivity=Cf / k, brine_conductivity=r.brine_tds / k,
        permeate_conductivity=r.permeate_tds / k,
        permeate_feed_side_conductivity=None, permeate_brine_side_conductivity=None,
        permeate_flow=r.permeate_flow, brine_flow=r.brine_flow, feed_temperature=T,
        brine_temperature=T, permeate_feed_side_temperature=T,
        permeate_brine_side_temperature=T,
    )
    return pd.DataFrame([row], columns=[c for c, _, _ in COLUMNS])


def _runs_from_df(df: pd.DataFrame, factor: float,
                  pressure_unit: str = "bar") -> tuple[list, list[str]]:
    runs, errors = [], []
    for i, row in df.iterrows():
        rid = row.get("run_id")
        if rid is None or (isinstance(rid, float) and math.isnan(rid)) or str(rid).strip() == "":
            if row.drop(labels=["run_id"]).notna().any():
                errors.append(f"row {i + 1}: missing Run ID")
            continue
        kwargs = {}
        for c, _, _ in COLUMNS:
            v = row.get(c)
            if v is None or (not isinstance(v, str) and pd.isna(v)):
                continue
            if c in STR_FIELDS:
                kwargs[c] = str(v)
            elif c in ("hpp_feed_pressure", "hpp_brine_pressure"):
                kwargs[c] = V.to_bar(float(v), pressure_unit)
            else:
                kwargs[c] = float(v)
        missing = [c for c in REQUIRED if c not in kwargs]
        if missing:
            errors.append(f"run {rid}: missing " + ", ".join(missing))
            continue
        runs.append(V.TestRun(**kwargs, ec_to_tds_factor=factor))
    return runs, errors


def _runs_to_df(runs) -> pd.DataFrame:
    rows = [{c: getattr(r, c) for c, _, _ in COLUMNS} for r in runs]
    return pd.DataFrame(rows, columns=[c for c, _, _ in COLUMNS])


# ---------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------
def _settings() -> tuple[float, float, float, dict, str]:
    with st.expander("Settings", expanded=False):
        c1, c2, c3 = st.columns(3)
        factor = c1.slider("EC → TDS factor (mg/L per μS/cm)", 0.55, 0.75,
                           V.DEFAULT_EC_TO_TDS, 0.01,
                           help="Applied to every run. 0.64 is a seawater factor.")
        fouling = c2.number_input("Fouling multiplier on Kw", 0.5, 1.2, 1.0, 0.01,
                                  help="1.0 = catalogue (clean) element. A what-if, not a fit.")
        health = c3.number_input("Pump health factor", 0.5, 1.2, 1.0, 0.01,
                                 help="1.0 = Danfoss reference flow.")
        pressure_unit = c1.radio(
            "Pressure unit in your readings", ["bar", "psi"], index=0, horizontal=True,
            help="The lab gauges read PSI; pick 'psi' and both pressure columns are "
                 "converted to bar automatically on entry. 1 PSI = 0.0689 bar.")
        st.markdown("**Tolerances** (± % of the measured value)")
        tol_df = pd.DataFrame([{"KPI": V.KPI_META[k][0], "key": k, "Tolerance (%)": v}
                               for k, v in V.DEFAULT_TOLERANCES.items()])
        edited = st.data_editor(
            tol_df, hide_index=True, disabled=["KPI", "key"],
            column_config={"key": None,
                           "Tolerance (%)": st.column_config.NumberColumn(min_value=0.0, step=0.5)},
            key="val_tol",
        )
        tolerances = {r["key"]: float(r["Tolerance (%)"]) for _, r in edited.iterrows()
                      if pd.notna(r["Tolerance (%)"])}
    return factor, fouling, health, tolerances, pressure_unit


def _test_runs(factor: float, pressure_unit: str = "bar") -> list:
    st.subheader("Test runs")
    if "val_runs_df" not in st.session_state:
        st.session_state.val_runs_df = _empty_runs()
    manual, upload = st.tabs(["Manual entry", "Upload CSV"])

    with manual:
        st.caption("One row per steady-state run. Column groups: Operator | Pressures | "
                   "Conductivities | Flows | Temperatures (sensor numbers from the plant "
                   "list). Feed flow is not entered — it is Qp + Qb. Optional columns may "
                   "be left blank.")
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Load example run", help="Adds the model-generated perfect-match run "
                     "(not plant data) to check the page end-to-end."):
            st.session_state.val_runs_df = pd.concat(
                [st.session_state.val_runs_df.dropna(how="all"), _example_run()],
                ignore_index=True)
            st.session_state.pop("val_editor", None)
        if b2.button("Clear runs"):
            st.session_state.val_runs_df = _empty_runs()
            st.session_state.pop("val_editor", None)
            st.session_state.pop("val_result", None)
        if pressure_unit == "psi":
            st.caption("Pressure unit = **PSI**: the two pressure columns are read as PSI "
                       "and converted to bar automatically.")
        cfg = {}
        for c, label, _ in COLUMNS:
            if c in ("hpp_feed_pressure", "hpp_brine_pressure"):
                label = label.replace("(bar)", f"({pressure_unit})")
            cfg[c] = (st.column_config.TextColumn(label) if c in STR_FIELDS else
                      st.column_config.NumberColumn(label, format="%.3f"))
        edited = st.data_editor(st.session_state.val_runs_df, num_rows="dynamic",
                                hide_index=True, column_config=cfg, key="val_editor",
                                width="stretch")
        runs, errors = _runs_from_df(edited, factor, pressure_unit)

    with upload:
        st.caption("CSV columns use the TestRun field names (run_id, hpp_feed_pressure, …); "
                   "blank cells are read as missing; unknown columns (pH, filter pressures) "
                   "are ignored.")
        f = st.file_uploader("Test-run CSV", type=["csv"])
        if f is not None:
            try:
                csv_runs = V.load_runs_csv(f, pressure_unit=pressure_unit)
                csv_runs = [dataclasses.replace(r, ec_to_tds_factor=factor) for r in csv_runs]
                st.dataframe(_runs_to_df(csv_runs), hide_index=True, width="stretch")
                if st.checkbox("Validate the uploaded runs instead of the manual table",
                               value=True):
                    runs, errors = csv_runs, []
            except (TypeError, ValueError) as exc:
                st.error(f"Could not read the CSV: {exc}")

    for e in errors:
        st.warning(e)
    return runs


# column help shared by the Level-2 comparison tables — written so the reader
# never has to guess what "predicted" or "Δ" mean, exactly as Level 1 does.
_CMP_HELP = {
    "KPI": "The quantity being compared, with its unit.",
    "Predicted": "The model's value (ŷ): what membrane.simulate computes from the "
                 "measured operating conditions (feed pressure, feed TDS, feed "
                 "temperature, Qf = Qp + Qb). No measurement of this quantity is used.",
    "Measured": "The plant value (y): read at the plant this run — the metered flow, "
                "or a conductivity reading converted to TDS, or the gauge ΔP.",
    "Abs err": "Absolute difference |ŷ − y|, in the KPI's own unit — how far the "
               "prediction is from the measurement.",
    "Rel err %": "Signed relative error 100·(ŷ − y)/|y|. Positive = the model "
                 "over-predicts, negative = it under-predicts.",
    "Tol %": "Acceptance threshold. |Rel err| at or below this counts as a match "
             "(🟢). Set in Settings.",
    "Status": "🟢 within tolerance · 🔴 outside it.",
}


def _cmp_table_v2(comps) -> pd.DataFrame:
    """Level-2 comparison table in the Level-1 visual style: predicted vs
    measured, the gap both ways (absolute and relative), and a coloured mark."""
    return pd.DataFrame([{
        "KPI": f"{V.KPI_META[c.name][0]} ({c.unit})",
        "Predicted": f"{c.predicted:.4g}",
        "Measured": f"{c.measured:.4g}",
        "Abs err": f"{c.absolute_error:.3g}",
        "Rel err %": "—" if math.isnan(c.relative_error_pct) else f"{c.relative_error_pct:+.1f}",
        "Tol %": f"{c.tolerance_pct:g}",
        "Status": _check_mark(c.within_tolerance),
    } for c in comps])


def _cmp_column_config() -> dict:
    return {k: st.column_config.TextColumn(k, help=v) for k, v in _CMP_HELP.items()}


def _level2_check(comps, block: str, caption: str) -> None:
    """Level 2 (model vs plant) — predicted vs measured, same open style as
    Level 1: how big each side is and how far apart they are, maths shown.
    Used for both the membrane block and the pump block."""
    passed = all(c.within_tolerance for c in comps)
    _status_badge(
        passed,
        f"Level 2 ({block}) — model matches the plant within tolerance on every KPI",
        f"Level 2 ({block}) — model and plant differ beyond tolerance on one or more KPIs",
    )
    st.caption(caption)
    st.dataframe(_cmp_table_v2(comps), hide_index=True, width="stretch",
                 column_config=_cmp_column_config())
    for c in comps:
        st.latex(c.worked)


def _status_badge(passed: bool, label_pass: str, label_fail: str) -> None:
    """A clear coloured status line: green check when passed, amber when not."""
    if passed:
        st.success(f"**{label_pass}**", icon=":material/check_circle:")
    else:
        st.warning(f"**{label_fail}**", icon=":material/error:")


def _check_mark(ok: bool) -> str:
    """Green check / red cross as coloured markdown, not a bare grey glyph."""
    return "🟢" if ok else "🔴"


def _data_consistency(dc) -> None:
    """Level 1 — raw-data self-consistency, every step shown. No model."""
    # Clear, self-contained status for Level 1 (independent of the model levels)
    _status_badge(
        dc.passed,
        "Level 1 verified — the raw readings are self-consistent (no model used)",
        "Level 1 failed — the raw readings break a conservation law or a sanity check",
    )
    st.caption("Level 1 · data self-consistency — conservation laws the measurements "
               "must satisfy on their own. These catch sensor or data-entry errors "
               "before any model runs. They prove the readings are self-consistent — "
               "not that they are free of a shared systematic error, which is why "
               "Levels 2–3 still follow.")

    # Balances — the FIRST side is predicted (the pump block computes the feed
    # flow from the VFD frequency via the Danfoss laws: Qf = Q_rated·(n/n_rated)·h),
    # the SECOND side is measured (the metered outlets, Qp + Qb). So the table is
    # Predicted vs Measured. The recovery-consistency row is NOT shown here: both
    # of its sides come from the same two meters, so it is an internal identity
    # (always ~0), not a predicted-vs-measured test — it would mislabel the columns.
    shown = [b for b in dc.balances if b.name != "recovery"]
    st.dataframe(
        pd.DataFrame([{
            "Balance": b.label,
            "Predicted": f"{b.lhs_label} = {b.lhs:.4g}",
            "Measured": f"{b.rhs_label} = {b.rhs:.4g}",
            "Unit": b.unit,
            "Closure %": f"{b.closure_pct:.2f}",
            "Tol %": f"{b.tolerance_pct:g}",
            "Status": _check_mark(b.closed),
        } for b in shown]),
        hide_index=True, width="stretch",
        column_config={
            "Balance": st.column_config.TextColumn(
                "Balance", help="The conservation law being checked: the pump-predicted "
                "feed flow must account for the metered outlets. This closes the loop "
                "around an unmetered feed — the plant does not measure feed flow directly."),
            "Predicted": st.column_config.TextColumn(
                "Predicted", help="The pump block's prediction, computed from the set VFD "
                "frequency through the Danfoss laws (n = 30·f; Qf = Q_rated·n/1500·health). "
                "For salt balance it is that predicted Qf times the measured feed TDS."),
            "Measured": st.column_config.TextColumn(
                "Measured", help="The plant reading: the metered permeate and brine flows "
                "(Qp + Qb), times their measured TDS for the salt balance. It must equal "
                "the predicted side if both the model and the meters are sound."),
            "Closure %": st.column_config.TextColumn(
                "Closure %", help="How far predicted and measured disagree, as a % of the "
                "larger side: 100·|predicted − measured| / max(|·|). Zero = perfect closure."),
            "Tol %": st.column_config.TextColumn(
                "Tol %", help="Acceptance threshold. Closure at or below this counts as "
                "closed (🟢). Set in Settings."),
            "Status": st.column_config.TextColumn(
                "Status", help="🟢 the balance closes within tolerance · 🔴 it does not."),
        },
    )
    for b in shown:
        st.latex(b.worked)

    st.markdown("_Sanity checks_ (physical plausibility of the raw readings)")
    st.dataframe(
        pd.DataFrame([{
            "Check": s.description, "Reading": s.detail,
            "Status": _check_mark(s.ok),
        } for s in dc.sanity]),
        hide_index=True, width="stretch",
        column_config={
            "Check": st.column_config.TextColumn(
                "Check", help="A physical-plausibility test on the raw readings alone — "
                "an impossible reading fails here even if every balance closes."),
            "Reading": st.column_config.TextColumn(
                "Reading", help="The measured values this check looked at."),
            "Status": st.column_config.TextColumn(
                "Status", help="🟢 physically plausible · 🔴 impossible, check the sensor."),
        },
    )

    for b in dc.balances:
        if not b.closed:
            st.warning(V.diagnose_balance(b))
    for s in dc.sanity:
        if not s.ok:
            st.warning(f"Sanity: {s.description} — {s.detail}")
    st.divider()


def _run_card(rv) -> None:
    r = rv.run
    with st.expander(f"Run {r.run_id}" + (f" · {r.timestamp}" if r.timestamp else ""),
                     expanded=len(st.session_state.val_result.runs) == 1):
        # Overall badge reflects BOTH levels, but names which level is the blocker
        # so a green Level 1 below is never contradicted by a bare red FAIL above.
        if rv.overall_pass:
            st.badge("PASS · both levels", icon=":material/check:", color="green")
        elif rv.data_consistency.passed:
            st.badge("Level 1 OK · Level 2 gap", icon=":material/check:", color="blue")
        else:
            st.badge("Level 1 failed", icon=":material/warning:", color="orange")
        if r.notes:
            st.caption(r.notes)

        _data_consistency(rv.data_consistency)
        _level2_check(
            rv.membrane_comparisons, "membrane",
            "Level 2 · model vs plant — the membrane model is driven by this run's "
            "measured operating conditions (feed pressure, feed TDS, feed temperature, "
            "Qf = Qp + Qb) and its prediction is compared with the plant reading. This "
            "measures the gap only; no parameter is adjusted.")
        st.divider()

        _level2_check(
            rv.pump_comparisons, "pump",
            "Level 2 · model vs plant — the pump's Danfoss flow law predicts the feed "
            "flow from the set VFD frequency (Qf = Q_rated·n/1500·health); it is compared "
            "with the mass-balance feed flow Qp + Qb. This measures the gap only; no "
            "parameter is adjusted.")

        mb = rv.mass_balance
        st.markdown("**Mass balance**")
        m1, m2, m3 = st.columns(3)
        m1.metric("Qf from pump (m³/h)", f"{mb['qfeed_pump']:.2f}", help=f"{mb['rpm']:.0f} rpm")
        m2.metric("Qf = Qp + Qb (m³/h)", f"{mb['qfeed_balance']:.2f}")
        m3.metric("Gap (%)", f"{mb['gap_pct']:+.1f}")
        st.latex(mb["worked"])
        for w in mb["pump_warnings"]:
            st.warning("Pump: " + w)

        vb = rv.valve_backsolve
        st.markdown("**Valve back-solve** (opening not measured)")
        v1, v2, v3 = st.columns(3)
        v1.metric("Opening (%)", f"{vb['opening_pct']:.1f}")
        v2.metric("ΔP achieved / target (bar)",
                  f"{vb['achieved_dp_bar']:.2f} / {vb['target_dp_bar']:.2f}")
        v3.metric("Converged", "✓" if vb["converged"] else "✗")
        st.latex(vb["worked"])
        st.caption("Cv curve is representative (valve block); the back-solved opening "
                   "inherits that assumption.")

        th = rv.thermal_consistency
        st.markdown("**Thermal consistency**")
        if th["n_other"] == 0:
            st.info("Only the feed temperature was recorded — nothing to cross-check.")
        elif th["isothermal"]:
            st.success(f"Isothermal within ±{th['tol_C']:.1f} °C ✓ "
                       f"(max |ΔT| = {th['max_delta_C']:.2f} °C)")
        else:
            st.warning(f"Not isothermal: max |ΔT| = {th['max_delta_C']:.2f} °C exceeds "
                       f"±{th['tol_C']:.1f} °C — check the thermometers or whether the run "
                       f"was at steady state.")
        st.latex(th["worked"])

        pg = rv.permeate_gradient
        if pg.get("available"):
            ok = pg["direction_ok"] and pg["mixed_between_ports"]
            st.markdown("**Permeate gradient** (dual-port, CH9 Fig. 10) " + ("✓" if ok else "✗"))
            st.dataframe(pd.DataFrame([
                {"Port": "Feed side (#9)", "TDS (mg/L)": f"{pg['feed_side_tds']:.1f}"},
                {"Port": "Mixed outlet (#7)", "TDS (mg/L)": f"{pg['mixed_tds']:.1f}"},
                {"Port": "Brine side (#10)", "TDS (mg/L)": f"{pg['brine_side_tds']:.1f}"},
            ]), hide_index=True)
            st.latex(pg["worked"])
            if not pg["direction_ok"]:
                st.warning("Brine-side permeate is not saltier than feed-side — check the "
                           "port probes or the sample lines.")
            if not pg["mixed_between_ports"]:
                st.warning("Mixed permeate is outside the two port readings — check the "
                           "mixed-outlet probe.")

        if not rv.overall_pass:
            st.markdown("**Diagnosis**")
            for c in rv.comparisons:
                if not c.within_tolerance:
                    st.warning(V.diagnose(c))


def _metrics(ds) -> None:
    st.subheader("Dataset metrics")
    st.caption("e = predicted − measured. Bias > 0 means the model over-predicts.")
    rows = [{
        "KPI": f"{V.KPI_META[k][0]} ({mt['unit']})", "n": mt["n"],
        "bias": f"{mt['bias']:+.4g}", "MAE": f"{mt['MAE']:.4g}",
        "RMSE": f"{mt['RMSE']:.4g}",
        "MAPE (%)": "—" if math.isnan(mt["MAPE"]) else f"{mt['MAPE']:.2f}",
    } for k, mt in ds.metrics.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _parity(ds, tolerances) -> None:
    st.subheader("Parity plots")
    st.caption("Predicted (x) vs measured (y). On the line = perfect; shaded = within "
               "tolerance.")
    run_ids = [rv.run.run_id for rv in ds.runs]
    colors = [RUN_COLORS[i] if i < len(RUN_COLORS) else OTHER for i in range(len(run_ids))]
    cols = st.columns(len(PARITY_KPIS))
    for col, key in zip(cols, PARITY_KPIS):
        label, unit, _ = V.KPI_META[key]
        pts = pd.DataFrame([{"run": rv.run.run_id, "predicted": c.predicted,
                             "measured": c.measured,
                             "rel": c.relative_error_pct}
                            for rv in ds.runs for c in rv.comparisons if c.name == key])
        if pts.empty:
            continue
        lo = min(pts.predicted.min(), pts.measured.min())
        hi = max(pts.predicted.max(), pts.measured.max())
        pad = max((hi - lo) * 0.15, abs(hi) * 0.05, 1e-6)
        dom = [lo - pad, hi + pad]
        t = tolerances.get(key, V.DEFAULT_TOLERANCES[key]) / 100.0
        xs = [dom[0] + (dom[1] - dom[0]) * i / 20 for i in range(21)]
        band = pd.DataFrame({"x": xs, "lo": [x / (1 + t) for x in xs],
                             "hi": [x / (1 - t) if t < 1 else dom[1] for x in xs]})
        scale = alt.Scale(domain=dom, nice=False)
        area = alt.Chart(band).mark_area(color=LINE, opacity=0.10, clip=True).encode(
            x=alt.X("x:Q", scale=scale, title=f"Predicted ({unit})"),
            y=alt.Y("lo:Q", scale=scale, title=f"Measured ({unit})"), y2="hi:Q")
        diag = alt.Chart(pd.DataFrame({"x": dom, "y": dom})).mark_line(
            color=LINE, strokeWidth=2, clip=True).encode(x="x:Q", y="y:Q")
        dots = alt.Chart(pts).mark_point(filled=True, size=120, stroke="#FFFFFF",
                                         strokeWidth=1.5).encode(
            x=alt.X("predicted:Q", scale=scale),
            y=alt.Y("measured:Q", scale=scale),
            color=alt.Color("run:N", scale=alt.Scale(domain=run_ids, range=colors),
                            legend=alt.Legend(title="Run")),
            shape=alt.Shape("run:N", legend=None),
            tooltip=[alt.Tooltip("run:N", title="run"),
                     alt.Tooltip("predicted:Q", format=".4g"),
                     alt.Tooltip("measured:Q", format=".4g"),
                     alt.Tooltip("rel:Q", format="+.1f", title="rel err %")])
        chart = (alt.layer(area, diag, dots)
                 .properties(title=f"{label} · ±{t*100:g}%", height=300)
                 .configure(background="transparent")
                 .configure_view(strokeWidth=0)
                 .configure_title(color=INK, fontSize=14, anchor="start")
                 .configure_axis(labelColor=INK, titleColor=INK, gridColor=GRID,
                                 domainColor=INK, tickColor=INK))
        col.altair_chart(chart, theme=None, width="stretch")


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
def render(controls: dict | None = None, feed: dict | None = None) -> None:
    st.header("Model vs plant — validation of the digital twin")
    st.caption(CAPTION)

    factor, fouling, health, tolerances, pressure_unit = _settings()
    runs = _test_runs(factor, pressure_unit)

    if st.button("Run validation", type="primary", disabled=not runs):
        st.session_state.val_result = V.validate_dataset(runs, tolerances, health, fouling)
        st.session_state.val_tolerances = tolerances
    if not runs:
        st.caption("Enter at least one complete run to validate.")

    ds = st.session_state.get("val_result")
    if ds is None:
        return
    used_tol = st.session_state.get("val_tolerances", tolerances)

    st.divider()
    n_pass = sum(rv.overall_pass for rv in ds.runs)
    n_data = sum(rv.data_consistency.passed for rv in ds.runs)
    st.caption(f"{n_data} of {len(ds.runs)} runs self-consistent (Level 1) · "
               f"{n_pass} of {len(ds.runs)} also pass model-vs-plant (Level 2)")
    st.subheader(f"Per-run results — {n_pass} of {len(ds.runs)} pass")
    for rv in ds.runs:
        _run_card(rv)

    st.divider()
    _metrics(ds)
    _parity(ds, used_tol)

    st.download_button("Download Markdown report", V.report_md(ds),
                       file_name="validation_report.md", mime="text/markdown")
