"""Membrane block as CH9 / report Chapter 3 Steps 1–7.

Reference values are the report's Tables 3.4–3.9 (rounded as printed).
Where the report states no tolerance, ±1 % is used — the report rounds
to 2–3 significant figures.
"""
import dataclasses
import json
import math
from pathlib import Path

import pytest

from core import membrane as m

REL = 0.01
BASELINE = Path(__file__).parent / "data" / "simulate_baseline.json"


def test_step1_matches_report():
    s = m.step1_preliminary_concentrations(41_000, 0.10)
    assert s["Cc"] == pytest.approx(45_546, rel=0.005)
    assert s["Cfc"] == pytest.approx(43_273, rel=0.005)
    assert s["Cp"] == pytest.approx(86.5, rel=0.005)
    assert set(s["worked"]) == {"cc", "cfc", "cp"}


def test_step2():
    s = m.step2_flux_and_flow(25)
    assert s["Qe"] == pytest.approx(1.02, rel=REL)
    assert "qe" in s["worked"]


def test_step3_matches_derivation():
    s = m.step3_permeabilities()
    assert s["Kw25"] == pytest.approx(0.99, rel=0.01)
    assert s["Ks25"] == pytest.approx(0.056, rel=0.01)
    # pre-refactor name still works and is the same function
    assert m.permeability_derivation is m.step3_permeabilities
    assert m.KW25 == s["Kw25"] and m.KS25 == s["Ks25"]


def test_step4_feed_pressure():
    s = m.step4_feed_pressure(25, 41_000, 0.10, temperature=25)
    assert s["Pfeed"] == pytest.approx(60, abs=1.0)
    assert s["NDP"] == pytest.approx(25.3, rel=REL)
    assert s["dpi"] == pytest.approx(34.3, rel=REL)
    assert set(s["worked"]) >= {"ndp", "pi_f", "pi_c", "pi_fc", "dpi", "pfeed"}


def test_step5_single_element():
    s = m.step5_flows_recovery_beta(60, 41_000, 25, 10.2)
    assert s["converged"]
    assert s["Qp"] == pytest.approx(1.04, rel=REL)
    assert s["Re"] == pytest.approx(0.102, rel=REL)
    assert s["beta"] == pytest.approx(1.10, rel=REL)
    assert s["ratio"] == pytest.approx(8.8, rel=REL)
    assert set(s["worked"]) >= {"cc", "ndp", "flux", "qp", "rec", "beta"}


def test_step6_two_formulations():
    s = m.step6_permeate_quality(43_328, 25.4, 25, 41_000)
    assert s["Cp_const_sr"] == pytest.approx(86.7, rel=REL)
    # report uses Ks rounded to 0.056; the derived Ks25 is 0.05575 → 95.1 vs 95.5
    assert s["Cp_flux_effect"] == pytest.approx(95.5, rel=REL)
    assert s["rejection"] == pytest.approx(0.998, abs=0.0005)
    assert set(s["worked"]) >= {"cp_const", "cp_flux", "rej"}


def test_step7_crossflow():
    s = m.step7_crossflow_velocity(10.2, 9.16)
    assert s["vfc"] == pytest.approx(0.22, rel=REL)
    assert s["Aeff"] == pytest.approx(0.0123, rel=REL)
    assert s["w"] == pytest.approx(20.4, rel=REL)
    assert s["Qfc"] == pytest.approx(9.68, rel=REL)


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a):
        return math.isnan(b)
    return a == b


def test_simulate_backward_compatible():
    """Baseline recorded from the pre-refactor simulate() (commit aa913be).
    Every original field — numbers, worked LaTeX, kpis, warnings — must be
    bit-identical."""
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert base, "baseline fixture is empty"
    for case in base:
        new = dataclasses.asdict(m.simulate(*case["inputs"]))
        for key, old in case["result"].items():
            assert _same(new[key], old), (case["inputs"], key, new[key], old)
            if isinstance(old, float):
                assert new[key] == pytest.approx(old, abs=1e-6)


def test_simulate_carries_all_seven_steps():
    r = m.simulate(60, 41_000, 25, 10.2)
    assert list(r.step_worked) == [f"step{i}" for i in range(1, 8)]
    assert r.crossflow_velocity == pytest.approx(0.22, rel=REL)
    assert r.qfc == pytest.approx(9.68, rel=REL)
    assert r.permeate_tds_const_sr == pytest.approx(86.6, rel=REL)


def test_envelope_warnings_still_fire():
    r = m.simulate(85, 41_000, 25, 10.2)
    assert any("max applied pressure" in w for w in r.warnings)
