"""Validation layer — model vs pilot-plant measurements."""
import copy
import math

import pytest

from core import membrane, pump, system, valve
from core import validation as V
from core.validation import TestRun

K = V.DEFAULT_EC_TO_TDS


def perfect_run(run_id="perfect", P=60.0, Cf=41_000.0, T=25.0, hz=60.0, **extra):
    """A TestRun whose measured fields equal the model's own outputs.
    Feed flow = what the pump delivers at `hz`, so the pump check matches too."""
    qf = system.feed_flow(hz)
    r = membrane.simulate(P, Cf, T, qf)
    return TestRun(
        run_id=run_id, vfd_frequency_hz=hz,
        hpp_feed_pressure=P, hpp_brine_pressure=P - r.element_dp,
        feed_conductivity=Cf / K, brine_conductivity=r.brine_tds / K,
        permeate_conductivity=r.permeate_tds / K,
        permeate_flow=r.permeate_flow, brine_flow=r.brine_flow,
        feed_temperature=T, **extra,
    )


def test_ec_to_tds():
    assert V.conductivity_to_tds(50_000) == pytest.approx(32_000)
    assert V.conductivity_to_tds(50_000, 0.64) == 32_000


def test_feed_flow_from_balance():
    run = TestRun(run_id="r", hpp_feed_pressure=60, hpp_brine_pressure=59.8,
                  feed_conductivity=64_000, brine_conductivity=71_000,
                  permeate_conductivity=150, permeate_flow=1.0, brine_flow=9.2,
                  feed_temperature=25)
    assert run.feed_flow == pytest.approx(10.2)
    assert run.element_dp_measured == pytest.approx(0.2)


def test_membrane_perfect_match():
    run = perfect_run()
    comps = V.validate_membrane_block(run)
    assert {c.name for c in comps} == {"permeate_flow", "permeate_tds", "brine_tds", "element_dp"}
    for c in comps:
        assert c.within_tolerance, c
        assert abs(c.relative_error_pct) < 1e-6
        assert c.worked
    rv = V.validate_run(run)
    assert rv.overall_pass


def test_valve_backsolve_round_trip():
    dp = valve.simulate(45, 9.2).delta_p
    b = V.backsolve_valve_opening(9.2, dp)
    assert b["converged"]
    assert b["opening_pct"] == pytest.approx(45, rel=0.005)
    assert b["achieved_dp_bar"] == pytest.approx(dp, abs=0.1)


def test_thermal_consistency_ok():
    run = TestRun(run_id="t", hpp_feed_pressure=60, hpp_brine_pressure=59.8,
                  feed_conductivity=64_000, brine_conductivity=71_000,
                  permeate_conductivity=150, permeate_flow=1.0, brine_flow=9.2,
                  feed_temperature=25, brine_temperature=25.3,
                  permeate_feed_side_temperature=25.1,
                  permeate_brine_side_temperature=25.4)
    t = V.thermal_consistency(run)
    assert t["isothermal"]
    assert t["n_other"] == 3
    assert t["max_delta_C"] == pytest.approx(0.4)


def test_permeate_gradient_direction():
    run = TestRun(run_id="g", hpp_feed_pressure=60, hpp_brine_pressure=59.8,
                  feed_conductivity=64_000, brine_conductivity=71_000,
                  permeate_conductivity=145, permeate_feed_side_conductivity=120,
                  permeate_brine_side_conductivity=180,
                  permeate_flow=1.0, brine_flow=9.2, feed_temperature=25)
    g = V.permeate_gradient_check(run)
    assert g["available"]
    assert g["direction_ok"] and g["mixed_between_ports"]
    assert g["gradient_mgL"] == pytest.approx(60 * K)
    assert run.permeate_tds_gradient == pytest.approx(60 * K)
    no_ports = perfect_run()
    assert V.permeate_gradient_check(no_ports) == {"available": False}


def test_dataset_aggregates():
    """Three runs with known permeate-flow gaps d (measured = predicted + d).
    Qb is lowered by d so the mass-balance feed flow — and therefore the
    prediction — is unchanged."""
    gaps = [0.05, -0.02, 0.10]
    base = perfect_run()
    pred = membrane.simulate(base.hpp_feed_pressure, base.feed_tds,
                             base.feed_temperature, base.feed_flow).permeate_flow
    runs = [TestRun(**{**base.__dict__, "run_id": f"r{i}",
                       "permeate_flow": base.permeate_flow + d,
                       "brine_flow": base.brine_flow - d})
            for i, d in enumerate(gaps)]
    ds = V.validate_dataset(runs)
    mt = ds.metrics["permeate_flow"]
    e = [-d for d in gaps]                          # predicted − measured
    meas = [pred + d for d in gaps]
    assert mt["n"] == 3
    assert mt["bias"] == pytest.approx(sum(e) / 3, abs=1e-3)
    assert mt["MAE"] == pytest.approx(sum(map(abs, e)) / 3, abs=1e-3)
    assert mt["RMSE"] == pytest.approx(math.sqrt(sum(x * x for x in e) / 3), abs=1e-3)
    assert mt["MAPE"] == pytest.approx(
        sum(abs(x) / y for x, y in zip(e, meas)) / 3 * 100, abs=1e-3)
    assert "feed_flow" in ds.metrics and "element_dp" in ds.metrics


def test_no_physics_changed():
    snap = (membrane.KW25, membrane.KS25, pump.v("rated_flow"),
            copy.deepcopy(membrane.PARAMS), copy.deepcopy(pump.CHARACTERISTICS),
            copy.deepcopy(valve.PARAMS))
    runs = [perfect_run("a"), perfect_run("b", P=55, T=28),
            perfect_run("c", P=65, Cf=38_000, T=30)]
    ds = V.validate_dataset(runs, tolerances={"permeate_flow": 1.0},
                            health=0.9, fouling=0.85)
    V.report_md(ds)
    after = (membrane.KW25, membrane.KS25, pump.v("rated_flow"),
             membrane.PARAMS, pump.CHARACTERISTICS, valve.PARAMS)
    assert after[0] == snap[0] and after[1] == snap[1] and after[2] == snap[2]
    assert after[3] == snap[3] and after[4] == snap[4] and after[5] == snap[5]
    d = membrane.step3_permeabilities()
    assert (d["Kw25"], d["Ks25"]) == (membrane.KW25, membrane.KS25)


def test_csv_round_trip(tmp_path):
    p = tmp_path / "runs.csv"
    p.write_text(
        "run_id,hpp_feed_pressure,hpp_brine_pressure,feed_conductivity,brine_conductivity,"
        "permeate_conductivity,permeate_flow,brine_flow,feed_temperature,brine_temperature,"
        "vfd_frequency_hz,pH\n"
        "R1,60,59.7,64000,71000,150,1.02,9.2,25,,,7.9\n", encoding="utf-8")
    (run,) = V.load_runs_csv(p)
    assert run.run_id == "R1" and run.brine_temperature is None
    assert run.vfd_frequency_hz == 60.0          # blank → default
    out = tmp_path / "report.md"
    V.save_report_md(V.validate_dataset([run]), out)
    assert "Run R1" in out.read_text(encoding="utf-8")
