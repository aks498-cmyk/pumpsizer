"""Digitise the KSB Multitec 50 Hz characteristic-curve booklet.

Like the Omega booklet, ``dow-multitec-data.pdf`` is a vector PDF with three
stacked charts (H per stage / NPSH / P) on a shared Q axis.  Differences:

* the heading is ``Multitec <size> <hydraulic>`` (e.g. ``Multitec 50 3.1``);
* **the head axis is per stage** - a real pump runs N equal stages, so total
  head = N x the digitised curve.  Table 9 on page 9 gives the maximum stage
  count (no balancing drum) per size and speed;
* the Q axis is labelled ``m3/h`` (not ``Q [m3/h]``); the ``US.gpm`` / ``IM.gpm``
  rows above the H chart are secondary scales;
* two impeller diameters per page.

Output: src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml - one entry per
(size, hydraulic, impeller, speed) with a per-stage ``curve:`` (Q vs H),
``stages_max``, NPSHr points and a BEP.  ``verified: false``, ``digitised: true``.

    py tools/digitise_ksb_multitec.py [path/to/dow-multitec-data.pdf]

Needs: pdfplumber, pyyaml, numpy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pdfplumber
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from digitise_ksb_omega import _f, _resample, _value_axis  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml"
NUM = re.compile(r"\d+(?:[.,]\d+)?$")
DEC = re.compile(r"[3-9][0-9][.,][0-9]$")
OD = re.compile(r"ø\s?(\d{2,3})")
HEAD = re.compile(r"Multitec\s*(\d{2,3})")
N = 9


def stage_limits(pdf) -> dict:
    """Parse Table 9 on page 9: {(size, hydraulic): {2900: (nmax, hmax), 1450: (nmax, hmax)}}."""
    p = pdf.pages[8]
    words = sorted(p.extract_words(), key=lambda w: (round(w["top"]), w["x0"]))
    rows: dict[int, list] = {}
    for w in words:
        if 275 < w["top"] < 400:
            rows.setdefault(round(w["top"]), []).append(w)
    out: dict = {}
    size = None
    for _, r in sorted(rows.items()):
        toks = [w["text"] for w in sorted(r, key=lambda w: w["x0"])]
        # rows look like:  [size?] hydraulic n2900 h2900 n1450 h1450 f
        if toks and re.fullmatch(r"\d{2,3}", toks[0]) and len(toks) >= 6:
            size = int(toks[0])
            toks = toks[1:]
        elif toks and re.fullmatch(r"\d+\.\d(?:/\d+\.\d)?", toks[0]):
            pass
        else:
            continue
        if size is None or not re.match(r"\d+\.\d", toks[0]):
            continue
        hyd = toks[0].split("/")[0]

        def g(i, _toks=toks):
            try:
                v = _toks[i]
                return None if v == "--" else int(v.replace(",", ""))
            except (IndexError, ValueError):
                return None

        out[(size, hyd)] = {2900: (g(1), g(2)), 1450: (g(3), g(4))}
        for extra in toks[0].split("/")[1:]:
            out[(size, extra)] = out[(size, hyd)]
    return out


def _stitch(segments, x_gap=45.0, y_gap=32.0):
    """Join polyline fragments whose x-ranges are adjacent and y is continuous.

    On Multitec pages a single H-Q (or NPSH) curve is drawn as several separate
    polyline objects, broken where efficiency contours cross it.  Chain the
    fragments back together: append the next segment when its left end is at
    (or just past) the current chain's right end and the y value carries on.
    """
    segs = [sorted(s, key=lambda p: p[0]) for s in segments if len(s) >= 2]
    segs.sort(key=lambda s: s[0][0])
    used = [False] * len(segs)
    chains = []
    for i, s in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        chain = list(s)
        moved = True
        while moved:
            moved = False
            cx, cy = chain[-1]
            for j, t in enumerate(segs):
                if used[j]:
                    continue
                if -6.0 <= t[0][0] - cx <= x_gap and abs(t[0][1] - cy) <= y_gap:
                    chain += t
                    used[j] = True
                    chain.sort(key=lambda p: p[0])
                    moved = True
                    break
        chains.append(chain)
    return chains


def _q_axis(words):
    lab = next((w for w in words if w["text"] in ("m3/h", "m³/h")), None)
    if not lab:
        return None
    y = (lab["top"] + lab["bottom"]) / 2
    pts = sorted(
        {
            ((w["x0"] + w["x1"]) / 2, _f(w["text"]))
            for w in words
            if abs((w["top"] + w["bottom"]) / 2 - y) < 4 and NUM.fullmatch(w["text"])
        }
    )
    if len(pts) < 4:
        return None
    a, b = np.polyfit([x for x, _ in pts], [v for _, v in pts], 1)
    pred = np.array([a * x + b for x, _ in pts])
    r2 = 1 - np.sum((pred - [v for _, v in pts]) ** 2) / max(
        np.var([v for _, v in pts]) * len(pts), 1e-9
    )
    return (float(a), float(b)) if r2 > 0.999 else None


def digitise_page(page, limits):
    text = page.extract_text() or ""
    hm = HEAD.search(text)
    if not hm:
        return None
    words = page.extract_words()
    size = int(hm.group(1))
    hyd = next(
        (w["text"] for w in words if w["top"] < 100 and re.fullmatch(r"\d+\.\d", w["text"])), None
    )
    rpm = 2900 if "2900" in text else (1450 if "1450" in text else None)
    if not (hyd and rpm):
        return {"size": size, "fail": "heading"}
    out = {"size": size, "hyd": hyd, "rpm": rpm, "datasheet_page": page.page_number}

    qax = _q_axis(words)
    if not qax:
        out["fail"] = "Q axis"
        return out
    qa, qb = qax

    m3h_rows = sorted((w["top"] + w["bottom"]) / 2 for w in words if w["text"] in ("m3/h", "m³/h"))
    ls_row = next(((w["top"] + w["bottom"]) / 2 for w in words if w["text"] == "l/s"), None)
    if len(m3h_rows) < 2 or not ls_row:
        out["fail"] = "bands"
        return out
    h_band = (95, m3h_rows[0] - 3)
    np_band = (ls_row + 3, (ls_row + m3h_rows[1]) / 2)

    h_ax = _value_axis(words, *h_band)
    np_ax = _value_axis(words, *np_band)
    if not h_ax:
        out["fail"] = "H axis"
        return out
    ha, hb = h_ax

    x_left = -qb / qa  # page x where Q = 0

    def band_segments(band):
        out = []
        for c in page.curves:
            pts = c["pts"]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if band[0] < np.mean(ys) < band[1] and max(xs) - min(xs) > 8:
                out.append(pts)
        return out

    def usable(pts, from_origin):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 55 or max(ys) - min(ys) < 10:
            return False
        # head / NPSH curves start at the Q=0 axis; efficiency contours don't
        return not from_origin or min(xs) < x_left + 30

    di = sorted({int(x) for x in OD.findall(text)}, reverse=True)
    heads = sorted(
        (ch for ch in _stitch(band_segments(h_band)) if usable(ch, True)),
        key=lambda pts: min(pts, key=lambda p: p[0])[1],
    )[: max(len(di), 1) + 1]
    npshs = (
        sorted(
            (ch for ch in _stitch(band_segments(np_band)) if usable(ch, True)),
            key=lambda pts: -max(p[0] for p in pts),
        )
        if np_ax
        else []
    )
    if not heads:
        out["fail"] = "no head curves"
        return out
    effs = sorted(
        ((_f(w["text"]), (w["x0"] + w["x1"]) / 2) for w in words if DEC.fullmatch(w["text"])),
        reverse=True,
    )
    lim = limits.get((size, hyd), {}).get(rpm, (None, None))
    stages_max, hmax_total = lim

    impellers = []
    for k, hpts in enumerate(heads[:3]):
        qh = [((qa * x + qb) / 3.6, ha * top + hb) for x, top in _resample(hpts, N)]
        qh = [(round(qv, 2), round(hv, 3)) for qv, hv in qh if hv > 0]
        if len(qh) < 5:
            continue
        qh[0] = (0.0, qh[0][1])
        q = [float(x) for x, _ in qh]
        h = [float(y) for _, y in qh]
        # each impeller in a family sits below the previous one at shut-off; a
        # heavily reduced one read deep into run-out can top a 2.7 ratio.
        prev_h0 = impellers[-1]["per_stage_h_m"][0] if impellers else float("inf")
        if not (all(b >= a - 1e-6 for a, b in zip(q, q[1:])) and h[0] > h[-1] and q[-1] > 0):
            continue
        if not (1.03 <= h[0] / max(h[-1], 0.1) <= 4.5 and h[0] < prev_h0 + 1e-6):
            continue
        npshr = None
        if np_ax and k < len(npshs):
            na, nb = np_ax
            cand = [
                (float(round((qa * x + qb) / 3.6, 2)), float(round(na * top + nb, 3)))
                for x, top in _resample(npshs[k], 6)
            ]
            vv = [v for _, v in cand]
            if all(0.2 <= v <= 20 for v in vv) and vv[-1] >= vv[0] - 0.3:
                npshr = cand
        eff_bep = q_bep = None
        if k < len(effs) and 45 < effs[k][0] < 92:
            eff_bep = float(round(effs[k][0], 1))
            q_bep = float(round((qa * effs[k][1] + qb) / 3.6, 2))
        impellers.append(
            {
                "diameter_mm": int(di[k]) if k < len(di) else None,
                "q_lps": q,
                "per_stage_h_m": h,
                "npshr": npshr,
                "eff_bep": eff_bep,
                "q_bep_lps": q_bep,
            }
        )

    if not impellers:
        out["fail"] = "no usable curves"
        return out
    out.update(
        impellers=impellers,
        stages_max=stages_max,
        hmax_total_m=hmax_total,
        digitised_ok=stages_max is not None,
    )
    if stages_max is None:
        out["fail"] = "no stage limit"
    return out


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "KSB/dow-multitec-data.pdf"
    pdf = pdfplumber.open(pdf_path)
    limits = stage_limits(pdf)
    # The booklet PDF carries the curve section twice (pages ~12-67 and ~68-127),
    # and the two copies are not identical - one may hold a size the other omits,
    # or read cleaner.  Keep the richest entry per (size, hydraulic, dia, rpm).
    by_key: dict = {}
    fails, pages_ok = [], 0

    def richness(e: dict) -> tuple:
        return (
            "npshr_points" in e,
            "eff_bep_pct" in e,
            len(e["curve"]["q_lps"]),
        )

    for page in pdf.pages:
        r = digitise_page(page, limits)
        if r is None:
            continue
        if r.get("fail") or not r.get("digitised_ok"):
            if r.get("fail") != "bands":  # the 2nd (single-m3/h) page of each size
                fails.append((r.get("size"), r.get("hyd"), r.get("rpm"), r.get("fail") or "sanity"))
            continue
        pages_ok += 1
        for k, imp in enumerate(r["impellers"]):
            dia = imp["diameter_mm"]
            nmax = r["stages_max"]
            h_total = [round(v * nmax, 2) for v in imp["per_stage_h_m"]]
            # cross-check the full-diameter shut-off head against Table 9's h_max
            tbl = r.get("hmax_total_m")
            secondary = r["hyd"].split(".")[-1] != "1"  # ".2" = reduced hydraulic
            delta = (h_total[0] - tbl) / tbl * 100.0 if tbl else None
            e = {
                "manufacturer": "KSB",
                "series": "Multitec",
                "model": f"{r['size']}/{r['hyd']}"
                + (f" ø{dia}" if dia else "")
                + f" ({r['rpm']}rpm)",
                "reference_speed_rpm": r["rpm"],
                "poles": 2 if r["rpm"] > 2000 else 4,
                "discharge_dn": r["size"],
                "impeller_diameter_mm": dia,
                # smaller of the two printed impellers -> let trim fall back to
                # the 0.80 default; larger one gets an explicit ~0.9 floor
                "min_impeller_diameter_mm": None if (k or not dia) else round(0.9 * dia),
                "stages_max": nmax,
                "per_stage_head_m": imp["per_stage_h_m"],
                "digitised": True,
                "verified": False,
                "datasheet_page": r["datasheet_page"],
                "source": "KSB Multitec 50 Hz Characteristic Curves Booklet; per-stage curve "
                "read from the vector PDF, x max stages (Table 9)",
                "notes": "machine-digitised per-stage curve x max stage count; fewer stages "
                "scale the head down pro rata. Confirm against the datasheet.",
                "curve": {"q_lps": imp["q_lps"], "h_m": h_total},
            }
            # Table 9's h_max is the full-diameter, primary-hydraulic figure -
            # only attach the cross-check where it actually applies (k == 0,
            # ".1" hydraulic).
            if delta is not None and k == 0 and not secondary:
                e["table9_hmax_total_m"] = tbl
                e["table9_delta_pct"] = round(delta, 1)
                if abs(delta) > 6:
                    e["notes"] += (
                        f" NOTE: digitised shut-off head is {delta:+.0f}% vs Table 9 "
                        f"({tbl} m) - the H axis on this page reads uncertainly; "
                        "check against the printed curve before design use."
                    )
            if imp["npshr"]:
                e["npshr_points"] = {
                    "q_lps": [q for q, _ in imp["npshr"]],
                    "value_m": [v for _, v in imp["npshr"]],
                }
            if imp["eff_bep"] and imp["q_bep_lps"]:
                e["eff_bep_pct"] = imp["eff_bep"]
                e["q_bep_lps"] = imp["q_bep_lps"]
            key = (r["size"], r["hyd"], dia, r["rpm"])
            if key not in by_key or richness(e) > richness(by_key[key]):
                by_key[key] = e

    entries = [by_key[k] for k in sorted(by_key, key=lambda t: (t[0], t[1], t[3], -(t[2] or 0)))]
    got = {
        (e["discharge_dn"], e["model"].split("/")[1].split(" ")[0], e["reference_speed_rpm"])
        for e in entries
    }
    fails = sorted({f for f in fails if (f[0], f[1], f[2]) not in got})

    hdr = (
        "# KSB Multitec, 50 Hz - high-pressure multistage pumps.\n"
        "# Per-stage H-Q curves machine-digitised from the vector PDF; curve: is the\n"
        "# per-stage head x the maximum stage count (Table 9, no balancing drum).\n"
        "# per_stage_head_m + stages_max let selection pick fewer stages.\n"
        "# verified: false - confirm against the printed datasheet before use.\n"
        "# Regenerate: py tools/digitise_ksb_multitec.py\n"
        f"# {len(entries)} curves from {pages_ok} pages, {len(fails)} skipped.\n\n"
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(hdr)
        fh.write(yaml.safe_dump({"pumps": entries}, sort_keys=False, allow_unicode=True))
    print(f"digitised {len(entries)} curves from {pages_ok} pages, {len(fails)} skipped -> {OUT}")
    for s, hy, rp, why in fails:
        print(f"  skip {s}/{hy} {rp}rpm  ({why})")


if __name__ == "__main__":
    main()
