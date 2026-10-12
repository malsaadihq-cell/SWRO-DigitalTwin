"""Membrane block — Hydranautics SWC4 MAX (single spiral-wound element).

Same design rule as the pump: nothing is a bare number. Every parameter
carries what it means and where it comes from, and every law is a named
function whose docstring cites its source.

Two sources are used:
  ESS  — Hydranautics SWC4 MAX element specification sheet
  CH9  — Salinas-Rodríguez et al., "Process design of reverse osmosis
         systems", IWA Publishing 2021, Chapter 9

Only the single-element solution-diffusion laws and the iteration logic
are taken from CH9; its worked example (a 72-element, 6-per-vessel,
40 % recovery plant) is NOT used — our plant is one element.

Measured quantities (feed pressure, feed TDS, temperature, feed flow)
are inputs the user records at the plant. Kw and Ks start from the values
the book derives from the element's standard test; they are parameters,
to be replaced by calibration once plant measurements exist.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ESS = "Hydranautics SWC4 MAX element specification sheet"
CH9 = "IWA 2021, Ch. 9"


@dataclass(frozen=True)
class Spec:
    value: float
    unit: str
    what: str
    source: str


PARAMS: dict[str, Spec] = {
    "area": Spec(40.9, "m²",
                 "Active membrane area of the element", ESS + " (also Ch. 9, Table 3)"),
    "Pfs": Spec(55.0, "bar",
                "Applied pressure in the element standard test", ESS),
    "Cfs": Spec(32000.0, "mg/L",
                "Feed NaCl concentration in the standard test", ESS),
    "Re_std": Spec(0.10, "—",
                   "Recovery in the standard test", ESS),
    "Qws": Spec(1.14, "m³/h",
                "Permeate flow in the standard test (27.3 m³/d)", ESS),
    "SR": Spec(0.998, "—",
               "Nominal salt rejection used for the brine-concentration build-up", ESS),
    "osmotic_coeff": Spec(0.8, "bar per 1000 mg/L",
                          "Osmotic-pressure rule of thumb", CH9 + ", p. 251"),
    "dPe": Spec(0.2, "bar",
                "Assumed head loss across one element", CH9 + ", p. 251"),
    "temp_coeff": Spec(1.03, "per °C",
                       "Permeability temperature factor (~3 % per °C)", CH9 + ", p. 251–252"),
    "pp_factor": Spec(0.01, "—",
                      "Permeate-side osmotic fraction for seawater", CH9 + ", p. 251, 258"),
    "Kp": Spec(0.99, "—",
               "Concentration-polarisation coefficient (Hydranautics)", CH9 + ", p. 258"),
    "Pp": Spec(0.0, "bar",
               "Permeate back-pressure (negligible)", CH9 + ", p. 254"),
}


def p(key: str) -> float:
    return PARAMS[key].value


def permeability_derivation() -> dict:
    """Compute Kw and Ks at 25 °C from the element standard-test performance
    on the spec sheet (IWA Ch. 9, p. 250–252). They are derived, not hand-entered."""
    Pfs, Cfs, Re, SR = p("Pfs"), p("Cfs"), p("Re_std"), p("SR")
    A, dPe, oc, ppf, Qws = p("area"), p("dPe"), p("osmotic_coeff"), p("pp_factor"), p("Qws")
    Ccs = Cfs * (1 - Re * (1 - SR)) / (1 - Re)
    pifc = (Cfs * oc / 1000 + Ccs * oc / 1000) / 2
    dpi = pifc - ppf * pifc
    NDPs = Pfs - dPe / 2 - dpi
    Jws = Qws * 1000.0 / A
    Kw25 = Jws / NDPs
    Cfcs = (Cfs + Ccs) / 2
    Cps = Cfcs * (1 - SR)
    Ks25 = Jws * Cps / Cfcs
    worked = {
        "ccs": (rf"C_{{cs}} = C_{{fs}}\frac{{1-R_e(1-SR)}}{{1-R_e}} = {Cfs:.0f}\,"
                rf"\frac{{1-0.1(1-0.998)}}{{0.9}} = {Ccs:.0f}\ \mathrm{{mg/L}}"),
        "ndps": (rf"NDP_s = P_{{fs}}-\tfrac{{\Delta P_e}}{{2}}-\Delta\pi = {Pfs:.0f}"
                 rf"-0.1-{dpi:.1f} = {NDPs:.1f}\ \mathrm{{bar}}"),
        "jws": (rf"J_{{ws}} = Q_{{ws}}\cdot 1000/A = {Qws:.2f}\cdot 1000/{A:.1f}"
                rf" = {Jws:.1f}\ \mathrm{{L/m^2 h}}"),
        "kw": (rf"K_w = J_{{ws}}/NDP_s = {Jws:.1f}/{NDPs:.1f} = {Kw25:.3f}"
               rf"\ \mathrm{{L/m^2\,bar\,h}}"),
        "cps": (rf"C_{{ps}} = C_{{fcs}}(1-SR) = {Cfcs:.0f}\times 0.002 = {Cps:.1f}"
                rf"\ \mathrm{{mg/L}}"),
        "ks": (rf"K_s = J_{{ws}}\,C_{{ps}}/C_{{fcs}} = {Jws:.1f}\times {Cps:.1f}/{Cfcs:.0f}"
               rf" = {Ks25:.3f}\ \mathrm{{L/m^2 h}}"),
    }
    return dict(Kw25=Kw25, Ks25=Ks25, worked=worked)


_DERIV = permeability_derivation()
KW25 = _DERIV["Kw25"]
KS25 = _DERIV["Ks25"]


# --- operating envelope (all from the ESS) ---------------------------
ENVELOPE = {
    "max_pressure": (82.7, "bar", "max applied pressure (1200 psig)"),
    "max_feed_flow": (17.0, "m³/h", "max feed flow per element"),
    "min_brine_flow": (2.7, "m³/h", "min brine flow per element"),
    "max_element_dp": (1.03, "bar", "max pressure drop per element (15 psi)"),
    "max_temp": (45.0, "°C", "max operating temperature"),
    "beta_max": (1.2, "—", "max concentration-polarisation factor"),
    "ratio_min": (5.0, "—", "min concentrate/permeate flow ratio"),
}


# ---------------------------------------------------------------------
# Laws (single element, CH9)
# ---------------------------------------------------------------------
def osmotic(conc_mgL: float) -> float:
    """Osmotic pressure from TDS: π = C × 0.8 / 1000  [bar]  (CH9 p. 251)."""
    return conc_mgL * p("osmotic_coeff") / 1000.0


def brine_conc(feed_tds: float, recovery: float) -> float:
    """Brine (concentrate) TDS build-up (CH9 p. 251):

        Cc = Cf · [1 − R(1 − SR)] / (1 − R)
    """
    sr = p("SR")
    return feed_tds * (1.0 - recovery * (1.0 - sr)) / (1.0 - recovery)


def kw_at(temperature: float, fouling: float) -> float:
    """Water permeability at temperature, with a fouling multiplier
    (1.0 = clean): Kw(T) = Kw25 · fouling · 1.03^(T−25)  (CH9 p. 252)."""
    return KW25 * fouling * p("temp_coeff") ** (temperature - 25.0)


def ks_at(temperature: float) -> float:
    """Salt permeability at temperature: Ks(T) = Ks25 · 1.03^(T−25)."""
    return KS25 * p("temp_coeff") ** (temperature - 25.0)


# ---------------------------------------------------------------------
# Result of one solved operating point
# ---------------------------------------------------------------------
@dataclass
class MembraneResult:
    feed_pressure: float
    feed_tds: float
    temperature: float
    feed_flow: float
    fouling: float

    permeate_flow: float      # Qp [m³/h]
    flux: float               # J  [L/m²·h]
    permeate_tds: float       # Cp [mg/L]
    rejection: float          # fraction
    recovery: float           # fraction
    ndp: float                # net driving pressure [bar]
    delta_pi: float           # Δπ [bar]
    brine_tds: float          # Cc [mg/L]
    brine_flow: float         # Qc [m³/h]
    cfc: float                # feed-concentrate avg TDS [mg/L]
    beta: float               # concentration-polarisation factor
    element_dp: float         # [bar]
    kw_T: float
    ks_T: float

    kpis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    worked: dict = field(default_factory=dict)
    converged: bool = True


def simulate(feed_pressure: float, feed_tds: float, temperature: float,
             feed_flow: float, fouling: float = 1.0) -> MembraneResult:
    """Solve the single element by iteration (CH9 element-1 procedure).

    Recovery is unknown because the brine concentration — and therefore
    the osmotic pressure and the flux — depend on it. We assume R, compute
    the flux and a new R, and repeat until it settles.
    """
    Kw = kw_at(temperature, fouling)
    Ks = ks_at(temperature)
    A = p("area")
    dPe = p("dPe")
    Pp = p("Pp")

    R = 0.10
    converged = False
    for _ in range(200):
        R = min(max(R, 0.0), 0.98)
        Cc = brine_conc(feed_tds, R)
        Cfc = (feed_tds + Cc) / 2.0
        pifc = (osmotic(feed_tds) + osmotic(Cc)) / 2.0
        dpi = pifc - p("pp_factor") * pifc
        ndp = feed_pressure - dPe / 2.0 - dpi - Pp
        if ndp <= 0.0:
            J = 0.0
            Qp = 0.0
        else:
            J = Kw * ndp
            Qp = J * A / 1000.0
        R_new = (Qp / feed_flow) if feed_flow > 0 else 0.0
        if abs(R_new - R) < 1e-6:
            R = R_new
            converged = True
            break
        R = 0.5 * R + 0.5 * R_new

    # final state at the settled recovery
    Cc = brine_conc(feed_tds, R)
    Cfc = (feed_tds + Cc) / 2.0
    pifc = (osmotic(feed_tds) + osmotic(Cc)) / 2.0
    dpi = pifc - p("pp_factor") * pifc
    ndp = feed_pressure - dPe / 2.0 - dpi - Pp
    J = Kw * ndp if ndp > 0 else 0.0
    Qp = J * A / 1000.0
    Cp = (Cfc * Ks / J) if J > 0 else 0.0
    rejection = (1.0 - Cp / feed_tds) if feed_tds > 0 else 0.0
    recovery = (Qp / feed_flow) if feed_flow > 0 else 0.0
    Qc = feed_flow - Qp
    Qfc = (feed_flow + Qc) / 2.0
    beta = p("Kp") * math.exp(Qp / Qfc) if Qfc > 0 else 0.0

    worked = {
        "cc": (rf"C_c = C_f\,\frac{{1-R(1-SR)}}{{1-R}} = {feed_tds:.0f}\,"
               rf"\frac{{1-{recovery:.3f}(1-0.998)}}{{1-{recovery:.3f}}} = {Cc:.0f}\ \mathrm{{mg/L}}"),
        "ndp": (rf"NDP = P_f - \tfrac{{\Delta P_e}}{{2}} - \Delta\pi - P_p"
                rf" = {feed_pressure:.1f} - 0.1 - {dpi:.1f} - 0 = {ndp:.1f}\ \mathrm{{bar}}"),
        "flux": (rf"J = K_w(T)\,NDP = {Kw:.3f}\times {ndp:.1f} = {J:.1f}\ \mathrm{{L/m^2 h}}"),
        "qp": (rf"Q_p = J\,A/1000 = {J:.1f}\times {A}/1000 = {Qp:.2f}\ \mathrm{{m^3/h}}"),
        "cp": (rf"C_p = \frac{{C_{{fc}}\,K_s(T)}}{{J}} = \frac{{{Cfc:.0f}\times {Ks:.3f}}}{{{J:.1f}}}"
               rf" = {Cp:.1f}\ \mathrm{{mg/L}}"),
        "rej": (rf"\text{{rejection}} = 1 - C_p/C_f = 1 - {Cp:.1f}/{feed_tds:.0f}"
                rf" = {rejection*100:.2f}\%"),
        "rec": (rf"R = Q_p/Q_f = {Qp:.2f}/{feed_flow:.2f} = {recovery*100:.1f}\%"),
        "kwT": (rf"K_w(T) = K_{{w,25}}\cdot 1.03^{{T-25}}\cdot h = {KW25:.3f}\cdot 1.03^{{{temperature:.0f}-25}}"
                rf"\cdot {fouling:.2f} = {Kw:.3f}\ \mathrm{{L/m^2\,bar\,h}}"),
        "ksT": (rf"K_s(T) = K_{{s,25}}\cdot 1.03^{{T-25}} = {KS25:.3f}\cdot 1.03^{{{temperature:.0f}-25}}"
                rf" = {Ks:.3f}\ \mathrm{{L/m^2 h}}"),
    }

    result = MembraneResult(
        feed_pressure=feed_pressure, feed_tds=feed_tds, temperature=temperature,
        feed_flow=feed_flow, fouling=fouling, permeate_flow=Qp, flux=J,
        permeate_tds=Cp, rejection=rejection, recovery=recovery, ndp=ndp,
        delta_pi=dpi, brine_tds=Cc, brine_flow=Qc, cfc=Cfc, beta=beta,
        element_dp=dPe, kw_T=Kw, ks_T=Ks, worked=worked, converged=converged,
    )
    result.kpis = {
        "permeate_flow": Qp,
        "flux": J,
        "rejection": rejection * 100.0,
        "recovery": recovery * 100.0,
        "permeate_tds": Cp,
        "brine_flow": Qc,
        "ratio": (Qc / Qp) if Qp > 0 else float("inf"),
        "ndp": ndp,
        "delta_pi": dpi,
    }
    result.warnings = _check_envelope(result)
    return result


def _check_envelope(r: MembraneResult) -> list[str]:
    w = []
    if r.feed_pressure > ENVELOPE["max_pressure"][0]:
        w.append(f"feed pressure {r.feed_pressure:.1f} bar is above the "
                 f"{ENVELOPE['max_pressure'][0]} bar max applied pressure (ESS)")
    if r.feed_flow > ENVELOPE["max_feed_flow"][0]:
        w.append(f"feed flow {r.feed_flow:.1f} m³/h is above the "
                 f"{ENVELOPE['max_feed_flow'][0]} m³/h max (ESS)")
    if r.brine_flow < ENVELOPE["min_brine_flow"][0]:
        w.append(f"brine flow {r.brine_flow:.1f} m³/h is below the "
                 f"{ENVELOPE['min_brine_flow'][0]} m³/h minimum (ESS)")
    if r.temperature > ENVELOPE["max_temp"][0]:
        w.append(f"temperature {r.temperature:.0f} °C is above the "
                 f"{ENVELOPE['max_temp'][0]:.0f} °C max (ESS)")
    if r.beta > ENVELOPE["beta_max"][0]:
        w.append(f"concentration-polarisation β = {r.beta:.2f} exceeds the "
                 f"{ENVELOPE['beta_max'][0]} guideline (ESS)")
    if r.permeate_flow > 0 and (r.brine_flow / r.permeate_flow) < ENVELOPE["ratio_min"][0]:
        w.append(f"concentrate/permeate ratio {r.brine_flow/r.permeate_flow:.1f} is "
                 f"below the 5:1 guideline (recovery too high)")
    return w


# ---------------------------------------------------------------------
# Interpretation (model vs a measured reading), CH9-consistent
# ---------------------------------------------------------------------
FLUX_TOL = 5.0
REJ_TOL = 0.3  # percentage points


def interpret(r: MembraneResult, measured: dict | None = None) -> list[tuple[str, str]]:
    msgs: list[tuple[str, str]] = []
    if r.fouling < 0.999:
        gap = (1.0 - r.fouling) * 100.0
        msgs.append(("info",
            f"Simulating fouling: the water permeability is set {gap:.0f}% below the "
            f"clean-element value, so the flux drops by about the same amount. On the "
            f"real element, a gap like this means scaling or fouling."))
    else:
        msgs.append(("info",
            "At 100% condition the model uses the catalogue permeability. Enter a measured "
            "reading to compare the real element against it."))

    if not measured:
        return msgs

    pf = measured.get("feed_pressure")
    qp = measured.get("permeate_flow")
    tm = measured.get("temperature", r.temperature)
    if pf and qp:
        clean = simulate(pf, r.feed_tds, tm, r.feed_flow, fouling=1.0)
        J_meas = qp * 1000.0 / p("area")
        gap = (J_meas - clean.flux) / clean.flux * 100.0 if clean.flux else 0.0
        if abs(gap) <= FLUX_TOL:
            msgs.append(("ok",
                f"Measured flux ({J_meas:.1f} LMH) matches the clean-element reference "
                f"within {gap:+.1f}% — the membrane is performing as specified."))
        elif gap < 0:
            msgs.append(("warn",
                f"Measured flux is {abs(gap):.1f}% BELOW the clean-element reference "
                f"(temperature already accounted for) → scaling or fouling is reducing "
                f"the water permeability."))
        else:
            msgs.append(("info",
                f"Measured flux is {gap:.1f}% ABOVE the reference — check the flow or "
                f"pressure reading, or recalibrate the permeability to this element."))

    cpm = measured.get("permeate_tds")
    if cpm and pf and qp:
        gap = (cpm - clean.permeate_tds)
        gap_pct = (cpm / r.feed_tds - clean.permeate_tds / r.feed_tds) * 100.0
        if gap > 0 and gap_pct > REJ_TOL:
            msgs.append(("warn",
                f"Measured permeate TDS ({cpm:.0f} mg/L) is higher than the reference "
                f"({clean.permeate_tds:.0f} mg/L) → increased salt passage, a sign of "
                f"membrane ageing or a seal leak."))
        else:
            msgs.append(("ok",
                f"Measured permeate TDS ({cpm:.0f} mg/L) is in line with the reference "
                f"({clean.permeate_tds:.0f} mg/L)."))
    return msgs


# ---------------------------------------------------------------------
# Reference curves for plotting
# ---------------------------------------------------------------------
def flux_reference(feed_tds, temperature, feed_flow, fouling=1.0,
                   lo=30.0, hi=85.0, points=34):
    out = []
    for i in range(points):
        pf = lo + (hi - lo) * i / (points - 1)
        out.append((pf, simulate(pf, feed_tds, temperature, feed_flow, fouling).flux))
    return out


def rejection_reference(feed_tds, temperature, feed_flow, fouling=1.0,
                        lo=30.0, hi=85.0, points=34):
    out = []
    for i in range(points):
        pf = lo + (hi - lo) * i / (points - 1)
        r = simulate(pf, feed_tds, temperature, feed_flow, fouling)
        out.append((pf, r.rejection * 100.0 if r.flux > 2.0 else None))
    return out


def flux_vs_temperature(feed_pressure, feed_tds, feed_flow, fouling=1.0,
                        lo=15.0, hi=42.0, points=28):
    """Flux sensitivity to feed temperature at the current pressure — the main
    confounder when reading field data (about 3 % per °C)."""
    out = []
    for i in range(points):
        T = lo + (hi - lo) * i / (points - 1)
        out.append((T, simulate(feed_pressure, feed_tds, T, feed_flow, fouling).flux))
    return out


def flux_vs_salinity(feed_pressure, temperature, feed_flow, fouling=1.0,
                     lo=30000.0, hi=50000.0, points=28):
    """Flux sensitivity to feed salinity at the current pressure — Red Sea feed
    TDS changes with season/intake."""
    out = []
    for i in range(points):
        Cf = lo + (hi - lo) * i / (points - 1)
        out.append((Cf, simulate(feed_pressure, Cf, temperature, feed_flow, fouling).flux))
    return out
