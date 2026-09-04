"""Digitise the KSB Omega / Omega V 50 Hz characteristic-curve booklet.

The booklet is a **vector** PDF: every H-Q, NPSH and power curve is a stroked
polyline, and the axis tick labels are positioned text.  This script calibrates
each size page from its tick labels and reads the curves back as data.

    py tools/digitise_ksb_omega.py [path/to/dow-omega-data.pdf]

Each size page has three charts stacked on a shared Q axis:  H (top),
NPSH (middle), P (bottom).  We locate the chart bands from the repeated
"Q [m3/h]" / "Q [l/s]" tick rows, calibrate each value axis from the
left-margin numeric ticks inside its band, then map the curve polylines
of **every impeller diameter** on the page to data.

Output: src/pumpsizer/data/catalog/ksb_omega_50hz.yaml - one entry per impeller
diameter, each with a real ``curve:`` (Q vs H) + NPSHr points + a BEP
(Q, efficiency).  Entries stay ``verified: false`` (machine-read) but
``digitised: true``; a page whose calibration fails sanity checks is skipped.

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

    def descends_lr(pts):
        """A real H-Q curve falls left-to-right (top-origin: y grows as H drops).
        A chart border - horizontal top or vertical side - does not, and must be
        filtered here so it doesn't consume an impeller-diameter slot."""
        s = sorted(pts, key=lambda p: p[0])
        n = max(len(s) // 3, 1)
        left = np.mean([p[1] for p in s[:n]])
        right = np.mean([p[1] for p in s[-n:]])
        return right - left > 12

    heads = [
        c["pts"] for c in page.curves if curve_band(c["pts"], h_band) and descends_lr(c["pts"])
    ]
    npshs = [c["pts"] for c in page.curves if np_ax and curve_band(c["pts"], np_band)]
    if not heads:
        out["fail"] = "no head curves"
        return out

    heads.sort(key=lambda pts: min(pts, key=lambda p: p[0])[1])  # highest shut-off first
    npshs.sort(key=lambda pts: -max(p[0] for p in pts))  # widest first (biggest impeller)
    ha, hb = h_ax
    di = sorted({int(x) for x in OD_RE.findall(text)}, reverse=True)
    effs = sorted(
        ((_f(w["text"]), (w["x0"] + w["x1"]) / 2) for w in words if DEC_RE.fullmatch(w["text"])),
        reverse=True,
    )

    def _npshr_for(k):
        if not (np_ax and k < len(npshs)):
            return None
        na, nb = np_ax
        cand = [
            (float(round((qa * x + qb) / 3.6, 2)), float(round(na * top + nb, 2)))
            for x, top in _resample(npshs[k], 6)
        ]
        vv = [v for _, v in cand]
        # a real NPSHr curve rises toward run-out; a flat trace is a border line
        ok = all(0.3 <= v <= 20 for v in vv) and vv[-1] > vv[0] and max(vv) - min(vv) >= 0.5
        return cand if ok else None

    impellers = []
    for k, hpts in enumerate(heads):
        qh = [((qa * x + qb) / 3.6, ha * top + hb) for x, top in _resample(hpts, N_SAMPLES)]
        qh = [(round(qv, 2), round(hv, 2)) for qv, hv in qh if hv > 0]
        if len(qh) < 5:
            continue
        qh[0] = (0.0, qh[0][1])
        q = [float(x) for x, _ in qh]
        h = [float(y) for _, y in qh]
        ratio = h[0] / max(h[-1], 0.1)
        # a small (heavily reduced) impeller read out to deep run-out can show a
        # shut-off/run-out ratio well above 2.7 - only reject the clearly broken
        prev_h0 = impellers[-1]["h_m"][0] if impellers else float("inf")
        if not (
            all(b >= a - 1e-6 for a, b in zip(q, q[1:]))
            and h[0] > h[-1]
            and 1.03 <= ratio <= 4.5
            and h[0] < prev_h0 + 1e-6  # in impeller-family order (largest first)
            and q[-1] > 0
        ):
            continue
        eff_bep = q_bep = None
        if k < len(effs) and 45 < effs[k][0] < 96:
            eff_bep = float(round(effs[k][0], 1))
            q_bep = float(round((qa * effs[k][1] + qb) / 3.6, 2))
        impellers.append(
            {
                "diameter_mm": int(di[k]) if k < len(di) else None,
                "q_lps": q,
                "h_m": h,
                "npshr": _npshr_for(k),
                "eff_bep": eff_bep,
                "q_bep_lps": q_bep,
                "shutoff_runout_ratio": round(float(ratio), 3),
            }
        )

    if not impellers:
        out["fail"] = "no usable impeller curves"
        return out

    out.update(
        impellers=impellers,
        impeller_options_mm=di or None,
        digitised_ok=True,
    )
    return out


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "KSB/dow-omega-data.pdf"
    pdf = pdfplumber.open(pdf_path)
    entries, fails, pages_ok = [], [], 0
    for page in pdf.pages:
        r = digitise_page(page)
        if r is None:
            continue
        if r.get("fail") or not r.get("digitised_ok"):
            fails.append((r["size"], r["rpm"], r.get("fail") or "sanity"))
            continue
        pages_ok += 1
        dn = int(r["size"].split("-")[0])
        imps = r["impellers"]
        for k, imp in enumerate(imps):
            dia = imp["diameter_mm"]
            tag = f" ø{dia}" if (dia and len(imps) > 1) else ""
            # the top impeller trims across the whole stock range; a smaller
            # stock impeller trims ~15% to bridge the gap to the next size
            smallest = min((i["diameter_mm"] for i in imps if i["diameter_mm"]), default=dia)
            min_dia = smallest if k == 0 else (round(0.87 * dia) if dia else None)
            e = {
                "manufacturer": "KSB",
                "series": "Omega",
                "model": f"{r['size']}{tag} ({r['rpm']}rpm)",
                "reference_speed_rpm": r["rpm"],
                "poles": 2 if r["rpm"] > 2000 else 4,
                "discharge_dn": dn,
                "impeller_diameter_mm": dia,
                "min_impeller_diameter_mm": min_dia,
                "impeller_options_mm": r["impeller_options_mm"],
                "digitised": True,
                "verified": False,
                "datasheet_page": r["datasheet_page"],
                "source": "KSB Omega / Omega V 50 Hz Characteristic Curves Booklet "
                "(15.02.2016); curve read from the vector PDF"
                + (f", impeller {dia} mm" if dia else ""),
                "notes": "machine-digitised from the datasheet curve; confirm against the "
                "printed page before design use",
                "curve": {"q_lps": imp["q_lps"], "h_m": imp["h_m"]},
            }
            if imp["npshr"]:
                e["npshr_points"] = {
                    "q_lps": [q for q, _ in imp["npshr"]],
                    "value_m": [v for _, v in imp["npshr"]],
                }
            if imp["eff_bep"] and imp["q_bep_lps"]:
                e["eff_bep_pct"] = float(imp["eff_bep"])
                e["q_bep_lps"] = float(imp["q_bep_lps"])
            entries.append(e)

    hdr = (
        "# KSB Omega / Omega V, 50 Hz - axially split volute casing pumps for water supply.\n"
        "# Curves machine-digitised from the vector PDF, one entry per impeller diameter:\n"
        "# Q vs H, NPSHr points, and a BEP (Q, efficiency).  verified: false - not\n"
        "# checked by a person; confirm against the printed datasheet page before use.\n"
        "# Regenerate: py tools/digitise_ksb_omega.py\n"
        f"# {len(entries)} curves from {pages_ok} size pages, {len(fails)} pages skipped.\n\n"
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(hdr)
        fh.write(yaml.safe_dump({"pumps": entries}, sort_keys=False, allow_unicode=True))
    print(f"digitised {len(entries)}, skipped {len(fails)} -> {OUT}")
    for s, rpm, why in fails:
        print(f"  skip {s} {rpm}rpm  ({why})")


if __name__ == "__main__":
    main()
