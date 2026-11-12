"""Experiment workbook reader — the data side of "Full system - with Experiments".

Reads the lab workbook (sheet "Readings": one row per parameter, one column
per experiment "Exp 1", "Exp 2", ...) and splits each experiment into the
three kinds of data the page needs:

    1. inputs      — the two knobs the twin is driven with:
                     VFD frequency (Hz) and brine-valve resistance K, computed here
                     from the run's own brine pressure and brine flow (K = P_b / Q_b²)
                     because the hand-wheel position is never recorded
    2. conditions  — feed salinity (TDS, mg/L) and feed temperature (°C)
    3. lab results — what the plant measured (plus quantities derived
                     directly from those measurements: Qf = Qp + Qb, R, J, rejection)

The number of experiments is detected from the header row, so adding a new
column "Exp 10" in Excel is enough — no code change.

Pure Python: no Streamlit here, so it can be unit-tested on its own.
Pressures in PSI are converted to bar ONCE, at load, using the unit column.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import openpyxl

PSI_TO_BAR = 0.0689476
MEMBRANE_AREA_DEFAULT = 40.9      # m², SWC4 MAX — overridden by core.membrane if passed

# Parameter-row labels in the workbook → internal key. Matched as a regex on the
# lower-cased label, first match wins, so the order matters for overlapping names.
ROW_PATTERNS: list[tuple[str, str]] = [
    ("frequency",      r"^frequency"),
    ("feed_tds",       r"^feed\s*salinity"),
    ("brine_ec",       r"^brine.*conductivity"),
    ("perm_ec",        r"^permeate\s*conductivity"),
    ("feed_ec",        r"feed\s*conductivity"),
    ("feed_temp",      r"^feed\s*temperature"),
    ("feed_pressure",  r"feed\s*pressure"),
    ("brine_pressure", r"brine\s*pressure"),
    ("permeate_flow",  r"^permeate\s*flow"),
    ("brine_flow",     r"^brine\s*flow"),
    ("permeate_tds",   r"^permeate.*salinity"),
    ("brine_tds",      r"^brine\s*salinity"),
    ("power",          r"power"),
    ("sec",            r"specific\s*energy"),
    ("beta",           r"polari[sz]ation"),
]

# Parameters block at the bottom of the sheet (label in col B, value in col C).
PARAM_PATTERNS: list[tuple[str, str]] = [
    ("k_feed", r"^k\s*\(feed\)"),
    ("k_brine", r"^k\s*\(brine\)"),
    ("k_perm", r"^k\s*\(product"),
]

EXP_HEADER = re.compile(r"^\s*exp(?:eriment)?\.?\s*(\d+)\s*$", re.IGNORECASE)


class WorkbookError(ValueError):
    """The workbook is not in the expected layout; the message says what is missing."""


@dataclass
class Experiment:
    number: int                      # the N in "Exp N"
    label: str                       # "Exp N" as written in the header
    raw: dict = field(default_factory=dict)        # key -> value as stored (after PSI→bar)
    units: dict = field(default_factory=dict)      # key -> unit text from the sheet
    labels: dict = field(default_factory=dict)     # key -> parameter label from the sheet
    notes: list = field(default_factory=list)      # conversions applied, readable

    # ---- 1. simulation inputs ------------------------------------------------
    @property
    def frequency(self):
        return self.raw.get("frequency")

    @property
    def valve_resistance(self):
        """Measured valve resistance K = P_brine / Q_brine²  [bar per (m³/h)²].
        Computed from the raw readings, not read from the sheet, so it does not
        depend on the workbook's formulas having been recalculated."""
        p, q = self.raw.get("brine_pressure"), self.raw.get("brine_flow")
        if p is None or not q:
            return None
        return p / q ** 2

    # ---- 2. conditions --------------------------------------------------------
    @property
    def feed_tds(self):
        return self.raw.get("feed_tds")

    @property
    def feed_temperature(self):
        return self.raw.get("feed_temp")


@dataclass
class Workbook:
    sheet: str
    experiments: list[Experiment]
    params: dict

    @property
    def count(self) -> int:
        return len(self.experiments)

    def get(self, number: int) -> Experiment:
        for e in self.experiments:
            if e.number == number:
                return e
        raise KeyError(number)


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _match(label: str, patterns) -> str | None:
    low = re.sub(r"\s+", " ", str(label)).strip().lower()
    for key, pat in patterns:
        if re.search(pat, low):
            return key
    return None


def _find_sheet(wb):
    for name in wb.sheetnames:
        if name.strip().lower() == "readings":
            return wb[name]
    # otherwise the first sheet that has an "Exp N" header
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=15, values_only=True):
            if any(isinstance(c, str) and EXP_HEADER.match(c) for c in row):
                return ws
    raise WorkbookError("No sheet with experiment columns (“Exp 1”, “Exp 2”, …) was found.")


def load_workbook(source) -> Workbook:
    """`source` is a path, bytes, or a file-like object (e.g. a Streamlit upload)."""
    if hasattr(source, "read"):
        data = source.read()
        source = io.BytesIO(data if isinstance(data, bytes) else data.encode())
    elif isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    wb = openpyxl.load_workbook(source, data_only=True, read_only=True)
    ws = _find_sheet(wb)
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    # ---- header row: the one holding "Exp N" cells -------------------------
    hdr_i = next((i for i, r in enumerate(rows)
                  if any(isinstance(c, str) and EXP_HEADER.match(c) for c in r)), None)
    if hdr_i is None:
        raise WorkbookError("No header row with “Exp 1”, “Exp 2”, … was found.")
    hdr = rows[hdr_i]
    low = [str(c).strip().lower() if c is not None else "" for c in hdr]
    label_col = low.index("parameter") if "parameter" in low else 1
    unit_col = low.index("unit") if "unit" in low else None
    exp_cols = [(j, int(EXP_HEADER.match(c).group(1)), c.strip())
                for j, c in enumerate(hdr) if isinstance(c, str) and EXP_HEADER.match(c)]

    # ---- parameter rows ------------------------------------------------------
    found: dict[str, tuple[int, str, str]] = {}      # key -> (row index, label, unit)
    params: dict[str, float] = {}
    for i in range(hdr_i + 1, len(rows)):
        r = rows[i]
        lab = r[label_col] if label_col < len(r) else None
        if not isinstance(lab, str) or not lab.strip():
            continue
        key = _match(lab, ROW_PATTERNS)
        if key and key not in found:
            unit = str(r[unit_col]).strip() if unit_col is not None and r[unit_col] else ""
            found[key] = (i, lab.strip(), unit)
            continue
        pkey = _match(lab, PARAM_PATTERNS)
        if pkey and pkey not in params:
            val = next((_num(c) for c in r[label_col + 1:label_col + 3] if _num(c) is not None), None)
            if val is not None:
                params[pkey] = val

    missing = [k for k in ("frequency", "brine_pressure", "brine_flow", "feed_temp")
               if k not in found]
    if "feed_tds" not in found and "feed_ec" not in found:
        missing.append("feed_tds")
    if missing:
        raise WorkbookError("These rows were not found on the sheet: " + ", ".join(missing))

    # ---- build one Experiment per column that actually holds data ----------
    exps: list[Experiment] = []
    for j, n, label in exp_cols:
        e = Experiment(number=n, label=label)
        for key, (i, lab, unit) in found.items():
            v = _num(rows[i][j]) if j < len(rows[i]) else None
            if v is None:
                continue
            if "psi" in unit.lower():
                e.notes.append(f"{lab}: {v:g} PSI → {v * PSI_TO_BAR:.2f} bar")
                v *= PSI_TO_BAR
                unit = "bar"
            e.raw[key], e.units[key], e.labels[key] = v, unit, lab
        if "feed_tds" not in e.raw and "feed_ec" in e.raw:
            k = params.get("k_feed", 0.66)
            e.raw["feed_tds"] = e.raw["feed_ec"] * k
            e.units["feed_tds"], e.labels["feed_tds"] = "mg/L", "Feed salinity (from EC)"
            e.notes.append(f"Feed TDS = EC × k = {e.raw['feed_ec']:g} × {k:g}")
        # salinity rows are formulas in the sheet; if their cached values are
        # missing, rebuild them from conductivity × k (same k as the sheet)
        for tds_key, ec_key, k_key, k_def, lab in (
                ("brine_tds", "brine_ec", "k_brine", 0.75, "Brine salinity (from EC)"),
                ("permeate_tds", "perm_ec", "k_perm", 0.5, "Permeate salinity (from EC)")):
            if tds_key not in e.raw and ec_key in e.raw:
                k = params.get(k_key, k_def)
                e.raw[tds_key] = e.raw[ec_key] * k
                e.units[tds_key], e.labels[tds_key] = "mg/L", lab
                e.notes.append(f"{lab} = EC × k = {e.raw[ec_key]:g} × {k:g}")
        if e.valve_resistance is not None:
            e.notes.append(f"Valve resistance K = P_b / Q_b² = {e.raw['brine_pressure']:.2f}"
                           f" / {e.raw['brine_flow']:.2f}² = {e.valve_resistance:.3f}"
                           " bar per (m³/h)²")
        # an empty future column ("Exp 10" with nothing under it) is not an experiment
        if e.frequency is not None and e.valve_resistance is not None:
            exps.append(e)

    if not exps:
        raise WorkbookError("Experiment columns were found but none holds a frequency, "
                            "a brine pressure and a brine flow.")
    exps.sort(key=lambda e: e.number)
    return Workbook(sheet=ws.title, experiments=exps, params=params)


# ---------------------------------------------------------------------------
# 3. Lab results, as the quantities the simulation predicts
# ---------------------------------------------------------------------------
@dataclass
class LabValue:
    value: float | None
    basis: str          # "measured" | "derived" | "workbook calc"
    how: str = ""       # LaTeX of how the derived value was formed ("" if measured)


def lab_results(e: Experiment, area: float = MEMBRANE_AREA_DEFAULT) -> dict[str, LabValue]:
    """Lab-side values keyed like the comparison rows. Derived values come only
    from this experiment's own measurements; nothing from the model."""
    g = e.raw.get
    out: dict[str, LabValue] = {}
    out["operating_pressure"] = LabValue(g("feed_pressure"), "measured")
    out["brine_pressure"] = LabValue(g("brine_pressure"), "sets K")
    qp, qb = g("permeate_flow"), g("brine_flow")
    out["permeate_flow"] = LabValue(qp, "measured")
    out["brine_flow"] = LabValue(qb, "measured")
    if qp is not None and qb is not None:
        qf = qp + qb
        out["feed_flow"] = LabValue(qf, "derived",
                                    rf"Q_f = Q_p + Q_b = {qp:.3f} + {qb:.3f} = {qf:.3f}\ \mathrm{{m^3/h}}")
        out["recovery"] = LabValue(100 * qp / qf if qf else None, "derived",
                                   rf"R = Q_p/(Q_p+Q_b) = {qp:.3f}/{qf:.3f} = {100 * qp / qf:.2f}\%")
    else:
        out["feed_flow"] = LabValue(None, "derived")
        out["recovery"] = LabValue(None, "derived")
    if qp is not None:
        j = qp * 1000.0 / area
        out["flux"] = LabValue(j, "derived",
                               rf"J = Q_p\cdot 1000/A_e = {qp:.3f}\times 1000/{area:g} = {j:.2f}\ \mathrm{{LMH}}")
    else:
        out["flux"] = LabValue(None, "derived")
    cp, cf = g("permeate_tds"), g("feed_tds")
    out["permeate_tds"] = LabValue(cp, "measured")
    out["brine_tds"] = LabValue(g("brine_tds"), "measured")
    if cp is not None and cf:
        rej = 100 * (1 - cp / cf)
        out["rejection"] = LabValue(rej, "derived",
                                    rf"\text{{rej}} = 1 - C_p/C_f = 1 - {cp:.1f}/{cf:.0f} = {rej:.2f}\%")
    else:
        out["rejection"] = LabValue(None, "derived")
    out["power"] = LabValue(g("power"), "workbook calc")
    out["sec"] = LabValue(g("sec"), "workbook calc")
    out["beta"] = LabValue(g("beta"), "workbook calc")
    return out
