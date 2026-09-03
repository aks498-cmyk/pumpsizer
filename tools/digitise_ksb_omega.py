"""Digitise the KSB Omega / Omega V 50 Hz characteristic-curve booklet.

The booklet is a **vector** PDF: every H-Q, NPSH and power curve is a stroked
polyline, and the axis tick labels are positioned text.  This script calibrates
each size page from its tick labels and reads the curves back as data.

    py tools/digitise_ksb_omega.py [path/to/dow-omega-data.pdf]

Each size page has three charts stacked on a shared Q axis:  H (top),
NPSH (middle), P (bottom).  We locate the chart bands from the repeated
"Q [m3/h]" / "Q [l/s]" tick rows, calibrate each value axis from the
left-margin numeric ticks inside its band, then map the curve polylines
(largest impeller) to data.

Output: src/pumpsizer/data/catalog/ksb_omega_50hz.yaml with real `curve:`
blocks (Q vs H) + NPSHr points + a BEP (Q, efficiency).  Entries stay
`verified: false` (machine-read) but `digitised: true`; a page whose
calibration fails sanity checks is skipped.

Needs: pdfplumber, pyyaml, numpy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pdfplumber
import yaml

OUT = Path(__file__).resolve().parents[1] / "src/pumpsizer/data/catalog/ksb_omega_50hz.yaml"
SIZE_RE = re.compile(r"Omega\s+(\d{3}-\d{3}[A-C]),\s*n\s*=\s*(\d+)\s*rpm")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?$")
DEC_RE = re.compile(r"[3-9][0-9][.,][0-9]$")
OD_RE = re.compile(r"ø\s?(\d{2,3})")
N_SAMPLES = 9


def _f(s):
    return float(str(s).replace(",", "."))


def _linfit(vals, px):
    v, x = np.asarray(vals, float), np.asarray(px, float)
    a, b = np.polyfit(x, v, 1)
    r2 = 1.0 - np.sum((v - (a * x + b)) ** 2) / max(np.sum((v - v.mean()) ** 2), 1e-12)
    return a, b, r2


def _resample(pts, n):
    p = np.asarray(sorted(pts, key=lambda q: q[0]), float)
    keep = np.concatenate(([True], np.diff(p[:, 0]) > 1e-6))
    p = p[keep]
    xs = np.linspace(p[0, 0], p[-1, 0], n)
    return list(zip(xs, np.interp(xs, p[:, 0], p[:, 1])))


def _q_axis(words):
    """Linear map  Q[m3/h] = a*x + b  from the 'Q [m3/h]' tick row."""
    label = next((w for w in words if "m³/h" in w["text"] or "m3/h" in w["text"]), None)
    if not label:
        return None
    yl = (label["top"] + label["bottom"]) / 2
    pts = []
    for w in words:
        if abs((w["top"] + w["bottom"]) / 2 - yl) < 4 and NUM_RE.fullmatch(w["text"]):
            pts.append(((w["x0"] + w["x1"]) / 2, _f(w["text"])))
    pts = sorted(set(pts))
    if len(pts) < 3:
        return None
    a, b, r2 = _linfit([v for _, v in pts], [x for x, _ in pts])
    return (a, b) if r2 > 0.999 else None


def _value_axis(words, top_lo, top_hi):
    """Linear map  value = a*top + b  from left-margin numeric ticks in the band."""
    ticks = []
    for w in words:
        yc = (w["top"] + w["bottom"]) / 2
        if w["x1"] < 146 and top_lo < yc < top_hi and NUM_RE.fullmatch(w["text"]):
            v = _f(w["text"])
            if v > 0:
                ticks.append((v, yc))
    # keep the largest self-consistent linear subset (guards stray annotations)
    ticks = sorted(set(ticks), key=lambda t: t[1])
    if len(ticks) < 2:
        return None
    best = None
    for i in range(len(ticks)):
        for j in range(i + 2, len(ticks) + 1):
            sub = ticks[i:j]
            a, b, r2 = _linfit([v for v, _ in sub], [y for _, y in sub])
            if r2 > 0.9995 and (best is None or len(sub) > best[0]):
                best = (len(sub), a, b)
    if best is None:
        a, b, r2 = _linfit([v for v, _ in ticks], [y for _, y in ticks])
        return (a, b) if r2 > 0.99 else None
    return best[1], best[2]


def digitise_page(page):
    text = page.extract_text() or ""
    m = SIZE_RE.search(text)
    if not m:
        return None
    size, rpm = m.group(1), int(m.group(2))
    words = page.extract_words()
    out = {"size": size, "rpm": rpm, "datasheet_page": page.page_number}

    qax = _q_axis(words)
    if not qax:
        out["fail"] = "Q axis"
        return out
    qa, qb = qax

    # chart bands from the two 'Q [m3/h]' rows and the 'Q [l/s]' row
    mh_rows = sorted(
        (w["top"] + w["bottom"]) / 2 for w in words if "m³/h" in w["text"] or "m3/h" in w["text"]
    )
    ls_row = next(((w["top"] + w["bottom"]) / 2 for w in words if "l/s" in w["text"]), None)
    if len(mh_rows) < 2:
        out["fail"] = "chart bands"
        return out
    h_band = (95, mh_rows[0] - 2)
    np_top = (ls_row + 2) if ls_row else mh_rows[0] + 15
    np_band = (np_top, (np_top + mh_rows[1]) / 2)

    h_ax = _value_axis(words, *h_band)
    np_ax = _value_axis(words, *np_band)
    if not h_ax:
        out["fail"] = "H axis"
        return out

    def curve_band(pts, band):
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        return (
            band[0] < np.mean(ys) < band[1]
            and max(xs) - min(xs) > 60  # spans the chart
            and max(ys) - min(ys) > 12
        )  # actually a curve, not a border line

    heads = [c["pts"] for c in page.curves if curve_band(c["pts"], h_band)]
    npshs = [c["pts"] for c in page.curves if np_ax and curve_band(c["pts"], np_band)]
    if not heads:
        out["fail"] = "no head curves"
        return out

    heads.sort(key=lambda pts: min(pts, key=lambda p: p[0])[1])  # highest shut-off first
    big = heads[0]
    ha, hb = h_ax
    qh = [((qa * x + qb) / 3.6, ha * top + hb) for x, top in _resample(big, N_SAMPLES)]
    qh = [(round(q, 2), round(h, 2)) for q, h in qh if h > 0]
    if len(qh) < 5:
        out["fail"] = "head curve too short"
        return out
    qh[0] = (0.0, qh[0][1])

    npshr = []
    if npshs and np_ax:
        na, nb = np_ax
        npshs.sort(key=lambda pts: -max(p[0] for p in pts))
        cand = [
            (round((qa * x + qb) / 3.6, 2), round(na * top + nb, 2))
            for x, top in _resample(npshs[0], 6)
        ]
        vals = [v for _, v in cand]
        if all(0.3 <= v <= 20 for v in vals) and vals[-1] >= vals[0] - 0.3:
            npshr = cand

    effs = [(_f(w["text"]), (w["x0"] + w["x1"]) / 2) for w in words if DEC_RE.fullmatch(w["text"])]
    eff_bep = q_bep = None
    if effs:
        e, ex = max(effs)
        if 45 < e < 96:
            eff_bep = round(e, 1)
            q_bep = round((qa * ex + qb) / 3.6, 2)

    q = [float(x) for x, _ in qh]
    h = [float(y) for _, y in qh]
    ratio = h[0] / max(h[-1], 0.1)
    ok = (
        all(b >= a - 1e-6 for a, b in zip(q, q[1:]))
        and h[0] > h[-1]
        and 1.03 <= ratio <= 2.7
        and q[-1] > 0
    )
    di = sorted({int(x) for x in OD_RE.findall(text)}, reverse=True)
    out.update(
        impeller_diameter_mm=max(di) if di else None,
        min_impeller_diameter_mm=min(di) if di else None,
        impeller_options_mm=di or None,
        q_lps=q,
        h_m=h,
        npshr=[(float(a), float(b)) for a, b in npshr] or None,
        eff_bep=float(eff_bep) if eff_bep else None,
        q_bep_lps=float(q_bep) if q_bep else None,
        shutoff_runout_ratio=round(float(ratio), 3),
        digitised_ok=bool(ok),
    )
    return out


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "KSB/dow-omega-data.pdf"
    pdf = pdfplumber.open(pdf_path)
    entries, fails = [], []
    for page in pdf.pages:
        r = digitise_page(page)
        if r is None:
            continue
        if r.get("fail") or not r.get("digitised_ok"):
            fails.append((r["size"], r["rpm"], r.get("fail") or "sanity"))
            continue
        dn = int(r["size"].split("-")[0])
        e = {
            "manufacturer": "KSB",
            "series": "Omega",
            "model": f"{r['size']} ({r['rpm']}rpm)",
            "reference_speed_rpm": r["rpm"],
            "poles": 2 if r["rpm"] > 2000 else 4,
            "discharge_dn": dn,
            "impeller_diameter_mm": r["impeller_diameter_mm"],
            "min_impeller_diameter_mm": r["min_impeller_diameter_mm"],
            "impeller_options_mm": r["impeller_options_mm"],
            "digitised": True,
            "verified": False,
            "datasheet_page": r["datasheet_page"],
            "source": "KSB Omega / Omega V 50 Hz Characteristic Curves Booklet (15.02.2016); "
            "curve read from the vector PDF, largest impeller",
            "notes": "machine-digitised from the datasheet curve; confirm against the "
            "printed page before design use",
            "curve": {"q_lps": r["q_lps"], "h_m": r["h_m"]},
        }
        if r["npshr"]:
            e["npshr_points"] = {
                "q_lps": [q for q, _ in r["npshr"]],
                "value_m": [v for _, v in r["npshr"]],
            }
        if r["eff_bep"] and r["q_bep_lps"]:
            e["eff_bep_pct"] = r["eff_bep"]
            e["q_bep_lps"] = r["q_bep_lps"]
        entries.append(e)

    hdr = (
        "# KSB Omega / Omega V, 50 Hz - axially split volute casing pumps for water supply.\n"
        "# Curves machine-digitised from the vector PDF (largest impeller per size):\n"
        "# Q vs H, NPSHr points, and a BEP (Q, efficiency).  verified: false - not\n"
        "# checked by a person; confirm against the printed datasheet page before use.\n"
        "# Regenerate: py tools/digitise_ksb_omega.py\n"
        f"# {len(entries)} sizes digitised, {len(fails)} skipped.\n\n"
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(hdr)
        fh.write(yaml.safe_dump({"pumps": entries}, sort_keys=False, allow_unicode=True))
    print(f"digitised {len(entries)}, skipped {len(fails)} -> {OUT}")
    for s, rpm, why in fails:
        print(f"  skip {s} {rpm}rpm  ({why})")


if __name__ == "__main__":
    main()
