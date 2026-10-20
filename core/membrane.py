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
    "element_length": Spec(1.0, "m",
                           "Element length Le (40-inch element)",
                           CH9 + ", p. 261 / Vrouwenvelder 2009"),
    "spacer_height": Spec(0.00071, "m",
                          "Feed-channel (spacer) height h",
                          CH9 + ", p. 261 / Vrouwenvelder 2009"),
    "spacer_porosity": Spec(0.85, "—",
                            "Feed-spacer porosity ε",
                            CH9 + ", p. 261 / Vrouwenvelder 2009"),
}


def p(key: str) -> float:
    return PARAMS[key].value


# ---------------------------------------------------------------------
# CH9 design procedure, Steps 1–7 (report Chapter 3, Section 3.3).
# Each step returns its numbers plus a `worked` dict of LaTeX bodies
# with the current values substituted. The number-of-elements and
# pressure-vessel parts of CH9 are omitted: the plant is one element.
# ---------------------------------------------------------------------
def step1_preliminary_concentrations(feed_tds: float, recovery: float) -> dict:
    """Step 1 — preliminary concentrations before iteration (CH9 p. 249):

        Cc  = Cf · [1 − R·(1−SR)] / (1 − R)
        Cfc = (Cf + Cc) / 2
        Cp  = Cfc · (1 − SR)
    """
    sr = p("SR")
    Cc = brine_conc(feed_tds, recovery)
    Cfc = (feed_tds + Cc) / 2.0
    Cp = Cfc * (1.0 - sr)
    worked = {
        "cc": (rf"C_c = C_f\,\frac{{1-R(1-SR)}}{{1-R}} = {feed_tds:.0f}\,"
               rf"\frac{{1-{recovery:.3f}(1-{sr})}}{{1-{recovery:.3f}}} = {Cc:.0f}\ \mathrm{{mg/L}}"),
        "cfc": (rf"C_{{fc}} = \frac{{C_f+C_c}}{{2}} = \frac{{{feed_tds:.0f}+{Cc:.0f}}}{{2}}"
                rf" = {Cfc:.0f}\ \mathrm{{mg/L}}"),
        "cp": (rf"C_p = C_{{fc}}(1-SR) = {Cfc:.0f}\times {1 - sr:.3f} = {Cp:.1f}\ \mathrm{{mg/L}}"),
    }
    return dict(Cc=Cc, Cfc=Cfc, Cp=Cp, worked=worked)


def step2_flux_and_flow(javg: float) -> dict:
    """Step 2 — design flux and permeate flow per element (CH9 p. 250):

        Qe = Javg · Ae / 1000      [m³/h]

    For a single-element plant the CH9 number-of-elements calculation
    reduces to 1 and is omitted.
    """
    A = p("area")
    Qe = javg * A / 1000.0
    worked = {
        "qe": (rf"Q_e = J_{{avg}}\,A_e/1000 = {javg:.1f}\times {A}/1000"
               rf" = {Qe:.2f}\ \mathrm{{m^3/h}}"),
    }
    return dict(Javg=javg, Qe=Qe, worked=worked)


def step3_permeabilities() -> dict:
    """Step 3 — Kw and Ks at 25 °C from the element standard-test performance
    on the spec sheet (CH9 p. 250–252). They are derived, not hand-entered."""
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


permeability_derivation = step3_permeabilities   # pre-refactor name, kept for imports

_DERIV = step3_permeabilities()
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
# CH9 Steps 4–7 (Steps 1–3 are above, before KW25/KS25 are fixed)
# ---------------------------------------------------------------------
def step4_feed_pressure(javg: float, feed_tds: float, recovery: float,
                        temperature: float = 25.0, fouling: float = 1.0) -> dict:
    """Step 4 — preliminary feed pressure for the chosen flux (CH9 p. 253–254):

        NDP   = Javg / Kw(T, fouling)
        Cc    = Cf · [1 − R·(1−SR)] / (1 − R)
        πf    = Cf · 0.8/1000,   πc = Cc · 0.8/1000
        πfc   = (πf + πc)/2,     πp = 0.01 · πfc
        Δπ    = πfc − πp
        ΔpPV  = ΔPe · 1                 (single element)
        Pfeed = NDP + ΔpPV/2 + Δπ + Pp
    """
    Kw = kw_at(temperature, fouling)
    dPe, Pp, ppf = p("dPe"), p("Pp"), p("pp_factor")
    ndp = javg / Kw if Kw > 0 else math.inf
    Cc = brine_conc(feed_tds, recovery)
    pi_f = osmotic(feed_tds)
    pi_c = osmotic(Cc)
    pi_fc = (pi_f + pi_c) / 2.0
    pi_p = ppf * pi_fc
    dpi = pi_fc - pi_p
    dpPV = dPe * 1
    Pfeed = ndp + dpPV / 2.0 + dpi + Pp
    worked = {
        "ndp": (rf"NDP = J_{{avg}}/K_w(T) = {javg:.1f}/{Kw:.3f} = {ndp:.1f}\ \mathrm{{bar}}"),
        "cc": (rf"C_c = C_f\,\frac{{1-R(1-SR)}}{{1-R}} = {feed_tds:.0f}\,"
               rf"\frac{{1-{recovery:.3f}(1-{p('SR')})}}{{1-{recovery:.3f}}} = {Cc:.0f}\ \mathrm{{mg/L}}"),
        "pi_f": (rf"\pi_f = C_f\cdot 0.8/1000 = {feed_tds:.0f}\times 0.0008 = {pi_f:.1f}\ \mathrm{{bar}}"),
        "pi_c": (rf"\pi_c = C_c\cdot 0.8/1000 = {Cc:.0f}\times 0.0008 = {pi_c:.1f}\ \mathrm{{bar}}"),
        "pi_fc": (rf"\pi_{{fc}} = \frac{{\pi_f+\pi_c}}{{2}} = \frac{{{pi_f:.1f}+{pi_c:.1f}}}{{2}}"
                  rf" = {pi_fc:.1f}\ \mathrm{{bar}},\quad \pi_p = {ppf}\,\pi_{{fc}} = {pi_p:.3f}\ \mathrm{{bar}}"),
        "dpi": (rf"\Delta\pi_{{avg}} = \pi_{{fc}}-\pi_p = {pi_fc:.1f}-{pi_p:.3f} = {dpi:.1f}\ \mathrm{{bar}}"),
        "pfeed": (rf"P_{{feed}} = NDP + \tfrac{{\Delta p_{{PV}}}}{{2}} + \Delta\pi_{{avg}} + P_p"
                  rf" = {ndp:.1f} + {dpPV / 2:.1f} + {dpi:.1f} + {Pp:.0f} = {Pfeed:.1f}\ \mathrm{{bar}}"),
    }
    return dict(NDP=ndp, Cc=Cc, pi_f=pi_f, pi_c=pi_c, pi_fc=pi_fc, pi_p=pi_p,
                dpi=dpi, dpPV=dpPV, Pfeed=Pfeed, worked=worked)


def step5_flows_recovery_beta(feed_pressure: float, feed_tds: float, temperature: float,
                              feed_flow: float, fouling: float = 1.0) -> dict:
    """Step 5 — flows, recovery and concentration polarisation (CH9 p. 254–258).

    Recovery is unknown because the brine concentration — and therefore
    the osmotic pressure and the flux — depend on it. Assume R → Cc, Δπ,
    NDP → J, Qp → new R, and repeat until it settles. Then:

        β   = Kp · exp(Qp / Qfc)        (CH9 p. 258)
        Qfc = (Qf + Qc)/2

    Deviation from the report's Table 3.7: the brine is concentrated with
    Cc = Cf·[1 − R(1−SR)]/(1 − R) (CH9 p. 251, as in Step 1/4), not with
    Cc1 = Cf1/(1 − Re1). The SR form is what simulate() has always used.
    """
    Kw = kw_at(temperature, fouling)
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
    recovery = (Qp / feed_flow) if feed_flow > 0 else 0.0
    Qc = feed_flow - Qp
    Qfc = (feed_flow + Qc) / 2.0
    beta = p("Kp") * math.exp(Qp / Qfc) if Qfc > 0 else 0.0
    ratio = (Qc / Qp) if Qp > 0 else math.inf

    worked = {
        "kwT": (rf"K_w(T) = K_{{w,25}}\cdot 1.03^{{T-25}}\cdot h = {KW25:.3f}\cdot 1.03^{{{temperature:.0f}-25}}"
                rf"\cdot {fouling:.2f} = {Kw:.3f}\ \mathrm{{L/m^2\,bar\,h}}"),
        "cc": (rf"C_c = C_f\,\frac{{1-R(1-SR)}}{{1-R}} = {feed_tds:.0f}\,"
               rf"\frac{{1-{recovery:.3f}(1-0.998)}}{{1-{recovery:.3f}}} = {Cc:.0f}\ \mathrm{{mg/L}}"),
        "ndp": (rf"NDP = P_f - \tfrac{{\Delta P_e}}{{2}} - \Delta\pi - P_p"
                rf" = {feed_pressure:.1f} - 0.1 - {dpi:.1f} - 0 = {ndp:.1f}\ \mathrm{{bar}}"),
        "flux": (rf"J = K_w(T)\,NDP = {Kw:.3f}\times {ndp:.1f} = {J:.1f}\ \mathrm{{L/m^2 h}}"),
        "qp": (rf"Q_p = J\,A/1000 = {J:.1f}\times {A}/1000 = {Qp:.2f}\ \mathrm{{m^3/h}}"),
        "rec": (rf"R = Q_p/Q_f = {Qp:.2f}/{feed_flow:.2f} = {recovery*100:.1f}\%"),
        "qc": (rf"Q_c = Q_f - Q_p = {feed_flow:.2f} - {Qp:.2f} = {Qc:.2f}\ \mathrm{{m^3/h}},\quad"
               rf"Q_{{fc}} = \frac{{Q_f+Q_c}}{{2}} = {Qfc:.2f}\ \mathrm{{m^3/h}}"),
        "beta": (rf"\beta = K_p\,e^{{Q_p/Q_{{fc}}}} = {p('Kp')}\,e^{{{Qp:.2f}/{Qfc:.2f}}}"
                 rf" = {beta:.2f}\quad(<{ENVELOPE['beta_max'][0]})"),
        "ratio": (rf"Q_c/Q_p = {Qc:.2f}/{Qp:.2f} = "
                  + (rf"{ratio:.1f}" if math.isfinite(ratio) else r"\infty")
                  + rf"\quad(>{ENVELOPE['ratio_min'][0]:.0f})"),
    }
    return dict(Re=recovery, Qp=Qp, Qc=Qc, Cc=Cc, Cfc=Cfc, Qfc=Qfc, J=J, NDP=ndp,
                dpi=dpi, beta=beta, ratio=ratio, converged=converged, Kw=Kw,
                worked=worked)


def step6_permeate_quality(cfc: float, flux: float, temperature: float,
                           feed_tds: float) -> dict:
    """Step 6 — permeate quality, two formulations side by side (CH9 p. 259):

        Cp (constant SR)  = Cfc · (1 − SR)
        Cp (flux effect)  = Cfc · Ks(T) / J      ← the one simulate() uses
        rejection         = 1 − Cp_flux / Cf
    """
    sr = p("SR")
    Ks = ks_at(temperature)
    Cp_const = cfc * (1.0 - sr)
    Cp = (cfc * Ks / flux) if flux > 0 else 0.0
    rejection = (1.0 - Cp / feed_tds) if feed_tds > 0 else 0.0
    worked = {
        "ksT": (rf"K_s(T) = K_{{s,25}}\cdot 1.03^{{T-25}} = {KS25:.3f}\cdot 1.03^{{{temperature:.0f}-25}}"
                rf" = {Ks:.3f}\ \mathrm{{L/m^2 h}}"),
        "cp_const": (rf"C_p = C_{{fc}}(1-SR) = {cfc:.0f}\times {1 - sr:.3f} = {Cp_const:.1f}"
                     rf"\ \mathrm{{mg/L}}"),
        "cp_flux": (rf"C_p = \frac{{C_{{fc}}\,K_s(T)}}{{J}} = \frac{{{cfc:.0f}\times {Ks:.3f}}}{{{flux:.1f}}}"
                    rf" = {Cp:.1f}\ \mathrm{{mg/L}}"),
        "rej": (rf"\text{{rejection}} = 1 - C_p/C_f = 1 - {Cp:.1f}/{feed_tds:.0f}"
                rf" = {rejection*100:.2f}\%"),
    }
    return dict(Cp_const_sr=Cp_const, Cp_flux_effect=Cp, rejection=rejection, Ks=Ks,
                worked=worked)


def step7_crossflow_velocity(qf: float, qc: float) -> dict:
    """Step 7 — cross-flow velocity in the feed channel (CH9 p. 261,
    spacer geometry after Vrouwenvelder 2009):

        Qfc  = (Qf + Qc)/2
        w    = (Ae / Le) / 2            [m]
        Aeff = ε · h · w                [m²]
        vfc  = (Qfc/3600) / Aeff        [m/s]
    """
    A, Le = p("area"), p("element_length")
    h, eps = p("spacer_height"), p("spacer_porosity")
    Qfc = (qf + qc) / 2.0
    w = (A / Le) / 2.0
    Aeff = eps * h * w
    vfc = (Qfc / 3600.0) / Aeff
    worked = {
        "w": rf"w = \frac{{A_e/L_e}}{{2}} = \frac{{{A}/{Le:g}}}{{2}} = {w:.2f}\ \mathrm{{m}}",
        "aeff": (rf"A_{{eff}} = \varepsilon\,h\,w = {eps}\times {h}\times {w:.2f}"
                 rf" = {Aeff:.4f}\ \mathrm{{m^2}}"),
        "vfc": (rf"v_{{fc}} = \frac{{Q_{{fc}}/3600}}{{A_{{eff}}}} = \frac{{{Qfc:.2f}/3600}}{{{Aeff:.4f}}}"
                rf" = {vfc:.2f}\ \mathrm{{m/s}}"),
    }
    return dict(Qfc=Qfc, w=w, Aeff=Aeff, vfc=vfc, worked=worked)


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

    permeate_tds_const_sr: float = 0.0   # Step 6, Cfc·(1−SR) [mg/L]
    crossflow_velocity: float = 0.0      # Step 7, vfc [m/s]
    qfc: float = 0.0                     # feed-concentrate avg flow [m³/h]
    step_worked: dict = field(default_factory=dict)   # {"step1": {...}, …, "step7": {...}}


def simulate(feed_pressure: float, feed_tds: float, temperature: float,
             feed_flow: float, fouling: float = 1.0) -> MembraneResult:
    """Solve the single element at a given feed pressure (CH9 element-1
    procedure): Step 5 (iteration) → Step 6 (permeate quality) → Step 7
    (cross-flow velocity).

    Steps 1, 2 and 4 are the design path (flux/recovery → pressure); they
    are evaluated at the solved flux and recovery only so their worked
    substitutions can be shown — they do not feed back into the result.
    """
    s5 = step5_flows_recovery_beta(feed_pressure, feed_tds, temperature, feed_flow, fouling)
    s6 = step6_permeate_quality(s5["Cfc"], s5["J"], temperature, feed_tds)
    s7 = step7_crossflow_velocity(feed_flow, s5["Qc"])

    R_design = min(max(s5["Re"], 0.0), 0.98)
    step_worked = {
        "step1": step1_preliminary_concentrations(feed_tds, R_design)["worked"],
        "step2": step2_flux_and_flow(s5["J"])["worked"],
        "step3": _DERIV["worked"],
        "step4": step4_feed_pressure(s5["J"], feed_tds, R_design, temperature, fouling)["worked"],
        "step5": s5["worked"],
        "step6": s6["worked"],
        "step7": s7["worked"],
    }

    Qp, J, Qc = s5["Qp"], s5["J"], s5["Qc"]
    Cp, rejection = s6["Cp_flux_effect"], s6["rejection"]
    worked = {
        "cc": s5["worked"]["cc"],
        "ndp": s5["worked"]["ndp"],
        "flux": s5["worked"]["flux"],
        "qp": s5["worked"]["qp"],
        "cp": s6["worked"]["cp_flux"],
        "rej": s6["worked"]["rej"],
        "rec": s5["worked"]["rec"],
        "kwT": s5["worked"]["kwT"],
        "ksT": s6["worked"]["ksT"],
    }

    result = MembraneResult(
        feed_pressure=feed_pressure, feed_tds=feed_tds, temperature=temperature,
        feed_flow=feed_flow, fouling=fouling, permeate_flow=Qp, flux=J,
        permeate_tds=Cp, rejection=rejection, recovery=s5["Re"], ndp=s5["NDP"],
        delta_pi=s5["dpi"], brine_tds=s5["Cc"], brine_flow=Qc, cfc=s5["Cfc"],
        beta=s5["beta"], element_dp=p("dPe"), kw_T=s5["Kw"], ks_T=s6["Ks"],
        worked=worked, converged=s5["converged"],
        permeate_tds_const_sr=s6["Cp_const_sr"], crossflow_velocity=s7["vfc"],
        qfc=s7["Qfc"], step_worked=step_worked,
    )
    recovery, ndp, dpi = s5["Re"], s5["NDP"], s5["dpi"]
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
# Component-level validation (model vs plant). Measures the gap only —
# no parameter is adjusted.
# ---------------------------------------------------------------------
VALIDATED_KPIS = ("permeate_flow", "permeate_tds", "brine_tds", "element_dp")


def validate_membrane(result: MembraneResult, measured: dict,
                      tolerances: dict | None = None) -> list["KpiComparison"]:
    """Compare the predicted permeate_flow, permeate_tds, brine_tds and
    element_dp against the measurements the caller supplies. Keys missing
    (or None) in `measured` are skipped. KpiComparison lives in
    core/validation.py and is imported lazily to avoid an import cycle."""
    from .validation import compare_kpi, merged_tolerances
    tol = merged_tolerances(tolerances)
    out = []
    for key in VALIDATED_KPIS:
        y = measured.get(key)
        if y is None:
            continue
        out.append(compare_kpi(key, getattr(result, key), y, tol[key]))
    return out


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
