"""Digitise the Lubi 6-inch stainless submersible bore-well catalogue.

``Lubi/Borehole_Submersible/6-Inch-SS-50-Hz-Catalogue.pdf`` is a vector PDF.
Each ``Performance curves`` page carries one **hydraulic** (the J-/W-series
impeller) drawn as a *family of stacked-stage curves*: one H-Q line per
available stage count (labelled 24 … 41 etc. down the left of the H chart),
each line being the per-stage head times that many stages.  Below it sit a
shared efficiency curve, a shared NPSH curve and a per-stage input-power curve.

Output: ``src/pumpsizer/data/catalog/lubi_6inch_50hz.yaml`` - one entry per
series, Multitec-style: ``per_stage_head_m`` + ``stages_max`` (+ the list of
catalogued counts), a shared BEP/efficiency and NPSHr.  ``digitised: true``,
``verified: false``.

    py tools/digitise_lubi_6inch.py [path/to/6-Inch-SS-50-Hz-Catalogue.pdf]

Needs: pdfplumber, pyyaml, numpy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pdfplumber
import yaml

OUT = Path(__file__).resolve().parents[1] / "src/pumpsizer/data/catalog/lubi_6inch_50hz.yaml"
FT_TO_M = 0.3048
MODEL_RE = re.compile(r"^[JW]\d{1,2}[A-Z]?$")
N = 9


def _f(s: str) -> float:
    return float(str(s).replace(",", "."))


def _linfit(vals, px):
    v, x = np.asarray(vals, float), np.asarray(px, float)
    a, b = np.polyfit(x, v, 1)
    r2 = 1.0 - np.sum((v - (a * x + b)) ** 2) / max(np.sum((v - v.mean()) ** 2), 1e-12)
    return float(a), float(b), float(r2)


def _resample(pts, n):
    p = np.asarray(sorted(pts, key=lambda q: q[0]), float)
    keep = np.concatenate(([True], np.diff(p[:, 0]) > 1e-6))
    p = p[keep]
    xs = np.linspace(p[0, 0], p[-1, 0], n)
    return list(zip(xs, np.interp(xs, p[:, 0], p[:, 1])))


def _q_axis(words):
    """Q [l/s] = a*x + b, from the 'm3/h' or 'l/sec' tick row (÷3.6 for m3/h)."""
    for label, div in (("l/sec", 1.0), ("m3/h", 3.6)):
        lab = next((w for w in words if w["text"] == label), None)
        if not lab:
            continue
        y = (lab["top"] + lab["bottom"]) / 2
        pts = sorted(
            {
                ((w["x0"] + w["x1"]) / 2, _f(w["text"]))
                for w in words
                if abs((w["top"] + w["bottom"]) / 2 - y) < 4 and re.fullmatch(r"\d+", w["text"])
            }
        )
        if len(pts) < 4:
            continue
        a, b, r2 = _linfit([v for _, v in pts], [x for x, _ in pts])
        if r2 > 0.9995:
            return a / div, b / div
    return None


def _h_axis(words, y_lo, y_hi):
    """H [m] = a*top + b, from the left-margin metre ticks of the H chart."""
    ticks = sorted(
        {
            (_f(w["text"]), (w["top"] + w["bottom"]) / 2)
            for w in words
            if w["x1"] < 100
            and y_lo < (w["top"] + w["bottom"]) / 2 < y_hi
            and re.fullmatch(r"\d{1,3}", w["text"])
        },
        key=lambda t: t[1],
    )
    if len(ticks) < 3:
        return None
    a, b, r2 = _linfit([v for v, _ in ticks], [y for _, y in ticks])
    return (a, b) if r2 > 0.999 else None


def _pct_axis(words, y_lo, y_hi):
    """efficiency % = a*top + b, from the 0..100 tick column at x ~85-98."""
    ticks = sorted(
        {
            (_f(w["text"]), (w["top"] + w["bottom"]) / 2)
            for w in words
            if w["x1"] < 105
            and y_lo < (w["top"] + w["bottom"]) / 2 < y_hi
            and re.fullmatch(r"\d{1,3}", w["text"])
            and 0 <= _f(w["text"]) <= 100
        },
        key=lambda t: t[1],
    )
    if len(ticks) < 3:
        return None
    a, b, r2 = _linfit([v for v, _ in ticks], [y for _, y in ticks])
    return (a, b) if r2 > 0.995 else None


def _stage_counts(page):
    """Stage-count labels down the left of the H chart, top (most) first.

    The labels sit at x ~146-160; the motor-kW column starts ~x176 - drop it,
    and cluster tightly so a label and its kW don't merge into one row.
    """
    chars = [c for c in page.chars if 144 < c["x0"] < 168 and 150 < c["top"] < 520]
    rows: dict[float, list] = {}
    for c in chars:
        yc = (c["top"] + c["bottom"]) / 2
        k = next((y for y in rows if abs(y - yc) < 4), yc)
        rows.setdefault(k, []).append(c)
    out = []
    for y, r in sorted(rows.items()):
        s = "".join(c["text"] for c in sorted(r, key=lambda c: c["x0"]) if c["x0"] < 166)
        if re.fullmatch(r"\d{2}", s) and 8 <= int(s) <= 60:
            out.append((int(s), y))
    # keep the strictly-descending run (guards a stray tick sneaking in)
    clean = []
    for cnt, y in out:
        if not clean or cnt < clean[-1][0]:
            clean.append((cnt, y))
    return clean  # [(count, y), ...] ascending y == descending count


def _band_curves(page, y_lo, y_hi, x_min_span, want_origin_x=None):
    out = []
    for c in page.curves:
        xs = [p[0] for p in c["pts"]]
        ys = [p[1] for p in c["pts"]]
        if not (y_lo < np.mean(ys) < y_hi and max(xs) - min(xs) > x_min_span):
            continue
        if want_origin_x is not None and min(xs) > want_origin_x + 12:
            continue
        out.append(sorted(c["pts"], key=lambda p: p[0]))
    return out


def _dedupe(curves, key_round=2.0):
    seen, out = set(), []
    for pts in curves:
        k = (
            round(min(pts, key=lambda p: p[0])[1] / key_round),
            round(max(p[0] for p in pts) / key_round),
            round(max(pts, key=lambda p: p[0])[1] / key_round),
        )
        if k in seen:
            continue
        seen.add(k)
        out.append(pts)
    return out


def digitise_page(page):
    words = page.extract_words()
    _ = page
    mdl = next(
        (w["text"] for w in words if MODEL_RE.match(w["text"]) and w["top"] < 135),
        None,
    )
    if not mdl:
        return None
    out = {"model": mdl, "page": page.page_number}

    qax = _q_axis(words)
    if not qax:
        out["fail"] = "Q axis"
        return out
    qa, qb = qax

    stages = _stage_counts(page)
    if len(stages) < 3:
        out["fail"] = f"stage labels ({len(stages)})"
        return out
    y_lo = min(y for _, y in stages) - 25
    y_hi = max(y for _, y in stages) + 40

    h_ax = _h_axis(words, y_lo - 10, y_hi + 40)
    if not h_ax:
        out["fail"] = "H axis"
        return out
    ha, hb = h_ax
    x_left = -qb / qa

    raw = _band_curves(page, y_lo, y_hi + 30, x_min_span=120, want_origin_x=x_left)
    curves = _dedupe(raw)
    curves.sort(key=lambda p: min(p, key=lambda q: q[0])[1])  # highest shut-off first
    n_want = len(stages)
    curves = curves[:n_want]
    if len(curves) < 3:
        out["fail"] = f"H curves ({len(curves)} for {n_want} stages)"
        return out

    # per-stage head: for each matched (count, curve), divide the curve by count,
    # then average the family onto a common Q grid
    counts = [c for c, _ in stages][: len(curves)]
    q_grid = None
    per_stage = []
    for cnt, pts in zip(counts, curves):
        qh = [((qa * x + qb), (ha * top + hb) / cnt) for x, top in _resample(pts, N)]
        qh = [(q, h) for q, h in qh if h > 0]
        if len(qh) < 5:
            continue
        q = np.array([p[0] for p in qh])
        h = np.array([p[1] for p in qh])
        if q_grid is None:
            q_grid = np.linspace(0.0, float(q[-1]), N)
        per_stage.append(np.interp(q_grid, q, h))
    if len(per_stage) < 3 or q_grid is None:
        out["fail"] = "per-stage build"
        return out
    ps = np.mean(per_stage, axis=0)
    if not (ps[0] > ps[-1] > 0 and np.all(np.diff(q_grid) > 0)):
        out["fail"] = "per-stage shape"
        return out
    # the stage family fans into a shared convergence point; drop that tail so
    # the curve keeps a sane shut-off/run-out ratio (<= 4) - the deep-run-out
    # end is below any usable operating point anyway
    cut = next((i for i in range(len(ps)) if ps[0] / ps[i] > 4.0), len(ps))
    cut = max(cut, 5)
    ps, q_grid = ps[:cut], q_grid[:cut]

    # shared efficiency curve: the p% band sits just under the H chart, between
    # its 'l/min' tick row and the 'PumpEff.'/'NPSH' block.
    eff_bep = q_bep = None
    npshr = None
    eff_lab = next((w for w in words if w["text"] in ("PumpEff.", "Pump")), None)
    lmin_rows = sorted((w["top"] + w["bottom"]) / 2 for w in words if w["text"] == "l/min")
    if eff_lab and lmin_rows:
        top_b = min(r for r in lmin_rows) + 6
        bot_b = (eff_lab["top"] + eff_lab["bottom"]) / 2 + 45
        ea = _pct_axis(words, top_b, bot_b)
        ec = _band_curves(page, top_b, bot_b, x_min_span=120, want_origin_x=x_left)
        if ec and ea:
            pts = max(ec, key=lambda p: max(x for x, _ in p) - min(x for x, _ in p))
            ev = [((qa * x + qb), ea[0] * top + ea[1]) for x, top in _resample(pts, 15)]
            ev = [(q, e) for q, e in ev if 0 < e < 100]
            if len(ev) >= 6:
                ei = int(np.argmax([e for _, e in ev]))
                peak, qp = ev[ei][1], ev[ei][0]
                # only trust it if the peak is in the plausible pump-eff band and
                # sits in the middle of the flow range (not at an end)
                if 45.0 <= peak <= 80.0 and 0.35 * q_grid[-1] <= qp <= 0.9 * q_grid[-1]:
                    eff_bep = float(round(peak, 1))
                    q_bep = float(round(qp, 2))

    out.update(
        series=mdl,
        counts=counts,
        stages_max=max(counts),
        q_lps=[float(round(x, 2)) for x in q_grid],
        per_stage_h_m=[float(round(x, 3)) for x in ps],
        eff_bep=eff_bep,
        q_bep_lps=q_bep,
        npshr=npshr,
        digitised_ok=True,
    )
    return out


def main():
    pdf_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "Lubi/Borehole_Submersible/6-Inch-SS-50-Hz-Catalogue.pdf"
    )
    pdf = pdfplumber.open(pdf_path)
    by_series: dict[str, dict] = {}
    fails = []
    for page in pdf.pages:
        r = digitise_page(page)
        if r is None:
            continue
        if r.get("fail") or not r.get("digitised_ok"):
            fails.append((r.get("model"), r.get("page"), r.get("fail") or "sanity"))
            continue
        # keep the richest page per series (widest stage range)
        cur = by_series.get(r["series"])
        if cur is None or len(r["counts"]) > len(cur["counts"]):
            by_series[r["series"]] = r

    entries = []
    for r in [v for _, v in sorted(by_series.items())]:
        nmax = r["stages_max"]
        e = {
            "manufacturer": "Lubi",
            "series": r["series"],
            "model": f"{r['series']} ({min(r['counts'])}-{nmax} stage)",
            "reference_speed_rpm": 2900,
            "poles": 2,
            "discharge_dn": 150,
            "stages": nmax,
            "stages_max": nmax,
            "catalogued_stage_counts": sorted(r["counts"]),
            "per_stage_head_m": r["per_stage_h_m"],
            "digitised": True,
            "verified": False,
            "datasheet_page": r["page"],
            "source": "Lubi 6-inch SS 50 Hz Borehole Submersible Catalogue; stacked-stage "
            "H-Q family read from the vector PDF, per-stage head averaged over the "
            "catalogued stage counts",
            "notes": "machine-digitised; per-stage curve x stage count. Efficiency is "
            "pump (not wire-to-water). Confirm against the printed page.",
            "curve": {
                "q_lps": r["q_lps"],
                "h_m": [round(v * nmax, 2) for v in r["per_stage_h_m"]],
            },
        }
        if r["eff_bep"] and r["q_bep_lps"]:
            e["eff_bep_pct"] = r["eff_bep"]
            e["q_bep_lps"] = r["q_bep_lps"]
        entries.append(e)

    hdr = (
        "# Lubi 6-inch stainless submersible bore-well pumps, 50 Hz.\n"
        "# Stacked-stage H-Q families machine-digitised from the vector PDF; one\n"
        "# entry per series with per_stage_head_m + stages_max (Multitec-style).\n"
        "# verified: false - confirm against the printed datasheet before use.\n"
        "# Regenerate: py tools/digitise_lubi_6inch.py\n"
        f"# {len(entries)} series, {len(fails)} pages skipped.\n\n"
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(hdr)
        fh.write(yaml.safe_dump({"pumps": entries}, sort_keys=False, allow_unicode=True))
    print(f"digitised {len(entries)} Lubi 6-inch series -> {OUT}")
    for m, p, why in fails:
        print(f"  skip {m} p{p}  ({why})")


if __name__ == "__main__":
    main()
