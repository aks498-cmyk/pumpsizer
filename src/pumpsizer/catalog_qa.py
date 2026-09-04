"""Quality checks for a pump catalogue - especially the machine-digitised ones.

The KSB Omega / Multitec entries are read off vector datasheets by
``tools/digitise_ksb_*.py`` and carry ``verified: false``.  ``check_catalog``
runs the sanity tests a person would otherwise do by eye:

* **shape** - Q ascending, H descending, a plausible shut-off/run-out ratio,
  BEP inside the curve, NPSHr positive and non-falling;
* **multistage** - ``curve.h_m`` really is ``per_stage_head_m x stages_max``,
  and (Multitec) that product matches the booklet's Table 9 maximum head;
* **affinity** - where the same pump appears at two speeds or two impeller
  diameters, the shut-off heads scale as ``n^2`` / ``D^2``.

Findings are ``OK`` / ``WARN`` / ``FAIL``.  ``pumpsizer catalog-check`` prints
them and exits non-zero if anything is ``FAIL``.

``verification_status`` / ``write_checklist`` back ``pumpsizer catalog-verify``:
the machine checks above can't replace a person comparing an entry with the
printed datasheet, so this emits the to-do list for that pass and tracks how
much of it is done (``verified: true``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .catalog import Catalog, PumpModel

_LEVELS = ("OK", "WARN", "FAIL")


@dataclass
class Finding:
    level: str  # OK | WARN | FAIL
    model: str
    check: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:4}  {self.model:34.34}  {self.check:11}  {self.message}"


def _family_stem(model: str) -> str:
    """Model name without the ``øNNN`` and ``(NNNN rpm)`` decorations."""
    s = re.sub(r"\s*\(\s*\d+\s*rpm\s*\)", "", model, flags=re.I)
    s = re.sub(r"\s*ø\s*\d+", "", s)
    return s.strip()


def _shape_findings(m: PumpModel) -> list[Finding]:
    out: list[Finding] = []
    key = m.key
    if not (m.q_lps and m.h_m):
        return out  # envelope-only entries are checked elsewhere
    q = np.asarray(m.q_lps, float)
    h = np.asarray(m.h_m, float)
    if len(q) < 4:
        out.append(Finding("WARN", key, "shape", f"only {len(q)} curve points"))
    if np.any(np.diff(q) < -1e-6):
        out.append(Finding("FAIL", key, "shape", "Q not ascending"))
    drops = np.diff(h)
    if np.any(drops > 0.05 * h[0]):
        out.append(Finding("FAIL", key, "shape", "H rises between points"))
    elif np.any(drops > 1e-6):
        out.append(Finding("WARN", key, "shape", "H not strictly descending"))
    if h[-1] > 0:
        ratio = h[0] / h[-1]
        if not 1.03 <= ratio <= 3.0:
            lvl = "FAIL" if ratio < 1.0 or ratio > 5.0 else "WARN"
            out.append(Finding(lvl, key, "shape", f"shut-off/run-out ratio {ratio:.2f}"))
    if h[-1] <= 0:
        out.append(Finding("FAIL", key, "shape", "last head <= 0"))

    q_bep = m.q_bep_lps
    if m.eff_bep_pct is not None:
        if not 35.0 <= m.eff_bep_pct <= 92.0:
            out.append(Finding("WARN", key, "bep", f"eff_bep {m.eff_bep_pct:.0f}% out of 35-92"))
        if q_bep is not None and not (q[0] - 1e-6 <= q_bep <= q[-1] + 1e-6):
            out.append(Finding("WARN", key, "bep", f"q_bep {q_bep:.1f} outside curve Q range"))

    if m.npshr_points:
        v = np.asarray(m.npshr_points.get("value_m", []), float)
        if v.size:
            if np.any(v < 0.1) or np.any(v > 25.0):
                out.append(Finding("WARN", key, "npshr", "NPSHr point outside 0.1-25 m"))
            if v[-1] < v[0] - 0.5:
                out.append(Finding("WARN", key, "npshr", "NPSHr falls with flow"))
    return out


def _multistage_findings(m: PumpModel) -> list[Finding]:
    out: list[Finding] = []
    if not m.is_multistage:
        return out
    key = m.key
    ps = np.asarray(m.per_stage_head_m, float)
    if len(ps) != len(m.q_lps):
        out.append(Finding("FAIL", key, "multistage", "per_stage_head_m length != q_lps"))
        return out
    got = np.asarray(m.h_m, float)
    want = ps * float(m.stages_max)
    if got.shape == want.shape and np.max(np.abs(got - want)) > 0.02 * max(want[0], 1.0):
        out.append(Finding("FAIL", key, "multistage", "curve.h_m != per_stage x stages_max"))
    t9 = getattr(m, "table9_hmax_total_m", None)
    if t9:
        d = (want[0] - t9) / t9 * 100.0
        if abs(d) > 12.0:
            out.append(Finding("WARN", key, "table9", f"shut-off {d:+.0f}% vs Table 9 {t9} m"))
        elif abs(d) > 6.0:
            out.append(Finding("OK", key, "table9", f"shut-off {d:+.0f}% vs Table 9 (noted)"))
    return out


def _h0(m: PumpModel) -> float | None:
    """Shut-off head for affinity comparison.  For a multistage pump this is the
    **per-stage** shut-off - the maximum stack count changes with speed, so the
    full-stack head does not scale as n^2 on its own."""
    try:
        stages = 1 if m.is_multistage else None
        return float(m.to_pump_curve(stages=stages).head(0.0))
    except Exception:
        return None


def _affinity_findings(models: list[PumpModel]) -> list[Finding]:
    out: list[Finding] = []

    # --- speed families: same stem + impeller diameter, differing rpm --------
    by_speed: dict[tuple, list[PumpModel]] = {}
    for m in models:
        if not (m.q_lps and m.h_m) or not m.reference_speed_rpm:
            continue
        by_speed.setdefault(
            (m.manufacturer, m.series, _family_stem(m.model), m.impeller_diameter_mm), []
        ).append(m)
    for grp in by_speed.values():
        grp = sorted(grp, key=lambda m: m.reference_speed_rpm)
        for lo, hi in zip(grp, grp[1:]):
            if hi.reference_speed_rpm == lo.reference_speed_rpm:
                continue
            h_lo, h_hi = _h0(lo), _h0(hi)
            if not h_lo or not h_hi:
                continue
            want = (hi.reference_speed_rpm / lo.reference_speed_rpm) ** 2
            got = h_hi / h_lo
            err = (got - want) / want * 100.0
            lvl = "OK" if abs(err) <= 12 else ("WARN" if abs(err) <= 25 else "FAIL")
            if lvl != "OK":
                out.append(
                    Finding(
                        lvl,
                        hi.key,
                        "affinity-n",
                        f"H0 ratio {got:.2f} vs n^2 {want:.2f} ({err:+.0f}%) "
                        f"[{lo.reference_speed_rpm:.0f}->{hi.reference_speed_rpm:.0f} rpm]",
                    )
                )

    # --- diameter families: same stem + rpm, differing impeller diameter ----
    by_dia: dict[tuple, list[PumpModel]] = {}
    for m in models:
        if not (m.q_lps and m.h_m) or not m.impeller_diameter_mm:
            continue
        by_dia.setdefault(
            (m.manufacturer, m.series, _family_stem(m.model), m.reference_speed_rpm), []
        ).append(m)
    for grp in by_dia.values():
        grp = sorted(grp, key=lambda m: m.impeller_diameter_mm)
        for sm, lg in zip(grp, grp[1:]):
            if lg.impeller_diameter_mm == sm.impeller_diameter_mm:
                continue
            h_sm, h_lg = _h0(sm), _h0(lg)
            if not h_sm or not h_lg:
                continue
            want = (lg.impeller_diameter_mm / sm.impeller_diameter_mm) ** 2
            got = h_lg / h_sm
            err = (got - want) / want * 100.0
            # trim isn't exactly D^2 and the reads are noisy - be lenient
            lvl = "OK" if abs(err) <= 18 else ("WARN" if abs(err) <= 35 else "FAIL")
            if lvl != "OK":
                out.append(
                    Finding(
                        lvl,
                        lg.key,
                        "affinity-D",
                        f"H0 ratio {got:.2f} vs D^2 {want:.2f} ({err:+.0f}%) "
                        f"[ø{sm.impeller_diameter_mm:.0f}->ø{lg.impeller_diameter_mm:.0f}]",
                    )
                )
    return out


def check_catalog(cat: Catalog) -> list[Finding]:
    """Every finding for a catalogue, worst level first."""
    models = list(cat)
    findings: list[Finding] = []
    for m in models:
        findings += _shape_findings(m)
        findings += _multistage_findings(m)
    findings += _affinity_findings(models)
    findings.sort(key=lambda f: (_LEVELS.index(f.level) * -1, f.model, f.check))
    return findings


def summarise(findings: list[Finding]) -> dict[str, int]:
    out = {lvl: 0 for lvl in _LEVELS}
    for f in findings:
        out[f.level] += 1
    return out


def format_report(cat: Catalog, findings: list[Finding], *, show_ok: bool = False) -> str:
    lines = [f"catalogue: {len(cat)} models"]
    shown = [f for f in findings if show_ok or f.level != "OK"]
    if not shown:
        lines.append("no warnings or failures")
    else:
        lines += [str(f) for f in shown]
    s = summarise(findings)
    lines.append(f"\n{s['FAIL']} FAIL   {s['WARN']} WARN   {s['OK']} OK-notes")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# verification tracking - a checklist for the human "against the paper
# datasheet" pass that flips ``verified: false`` -> ``true``.
# ---------------------------------------------------------------------------
_CHECKLIST_COLS = (
    "verified",
    "manufacturer",
    "series",
    "model",
    "datasheet_page",
    "shutoff_head_m",
    "q_bep_lps",
    "eff_bep_pct",
    "npshr_at_bep_m",
    "qa",  # worst QA level for this model, if any
    "verdict",  # <- fill: ok | corrected | reject
    "checked_by",  # <- fill
    "checked_date",  # <- fill
    "notes",  # <- fill
)


def _npshr_at_bep(m: PumpModel) -> float | str:
    try:
        c = m.to_pump_curve()
        qb, _, _ = c.bep()
        v = float(c.npshr(qb))
        return round(v, 2) if v == v else ""
    except Exception:
        return ""


def verification_rows(cat: Catalog, findings: list[Finding] | None = None) -> list[dict]:
    """One checklist row per digitised, not-yet-verified model."""
    worst: dict[str, str] = {}
    for f in findings or []:
        if f.model not in worst or _LEVELS.index(f.level) > _LEVELS.index(worst[f.model]):
            worst[f.model] = f.level
    rows = []
    for m in cat:
        if m.verified or not getattr(m, "digitised", False):
            continue
        try:
            so = round(float(m.to_pump_curve().head(0.0)), 1)
        except Exception:
            so = ""
        rows.append(
            {
                "verified": m.verified,
                "manufacturer": m.manufacturer,
                "series": m.series,
                "model": m.model,
                "datasheet_page": m.datasheet_page or "",
                "shutoff_head_m": so,
                "q_bep_lps": m.q_bep_lps or "",
                "eff_bep_pct": m.eff_bep_pct or "",
                "npshr_at_bep_m": _npshr_at_bep(m),
                "qa": worst.get(m.key, ""),
                "verdict": "",
                "checked_by": "",
                "checked_date": "",
                "notes": "",
            }
        )
    return rows


def write_checklist(cat: Catalog, path, findings: list[Finding] | None = None) -> int:
    """Write the verification checklist as CSV; returns the row count."""
    import csv
    from pathlib import Path

    rows = verification_rows(cat, findings)
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(_CHECKLIST_COLS))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def verification_status(cat: Catalog) -> dict[str, dict[str, int]]:
    """{series: {verified, digitised_unverified, other}} plus a 'TOTAL' key."""
    out: dict[str, dict[str, int]] = {}
    for m in cat:
        b = out.setdefault(m.series, {"verified": 0, "to_check": 0, "other": 0})
        if m.verified:
            b["verified"] += 1
        elif getattr(m, "digitised", False):
            b["to_check"] += 1
        else:
            b["other"] += 1
    tot = {"verified": 0, "to_check": 0, "other": 0}
    for b in out.values():
        for k in tot:
            tot[k] += b[k]
    out["TOTAL"] = tot
    return out
