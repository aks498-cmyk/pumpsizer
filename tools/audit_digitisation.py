"""Page-level audit of the digitised KSB catalogues against the source PDFs.

`catalog-check` works on the emitted YAML; this goes back to the datasheet and
asks, per page:

* **curves dropped** - the classifier emitted fewer impeller curves than there
  are distinct H-band strokes on the page;
* **diameter labels** - the number of emitted impellers doesn't match the
  number of ``ø`` labels in the page text (likely a mis-labelled diameter);
* **truncated** - the digitised curve stops well short of the printed stroke's
  right-hand (max-Q) end.

It ranks the pages worst-first so the human datasheet pass can start there.

    py tools/audit_digitisation.py [--csv audit.csv]
        [--omega-pdf KSB/dow-omega-data.pdf] [--multitec-pdf KSB/dow-multitec-data.pdf]

Needs: pdfplumber, pyyaml, numpy.
"""

from __future__ import annotations

import csv as _csv
import sys
from pathlib import Path

import numpy as np
import pdfplumber
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from digitise_ksb_multitec import HEAD as MT_HEAD  # noqa: E402
from digitise_ksb_multitec import OD as MT_OD  # noqa: E402
from digitise_ksb_multitec import _q_axis as mt_q_axis  # noqa: E402
from digitise_ksb_multitec import _stitch  # noqa: E402
from digitise_ksb_omega import OD_RE, SIZE_RE  # noqa: E402
from digitise_ksb_omega import _q_axis as om_q_axis  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OMEGA_YAML = ROOT / "src/pumpsizer/data/catalog/ksb_omega_50hz.yaml"
MULTITEC_YAML = ROOT / "src/pumpsizer/data/catalog/ksb_multitec_50hz.yaml"


def _entries_by_page(path: Path) -> dict[int, list[dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["pumps"]
    out: dict[int, list[dict]] = {}
    for e in data:
        p = e.get("datasheet_page")
        if p:
            out.setdefault(int(p), []).append(e)
    return out


def _omega_page_strokes(page):
    words = page.extract_words()
    qax = om_q_axis(words)
    mh = sorted(
        (w["top"] + w["bottom"]) / 2 for w in words if "m³/h" in w["text"] or "m3/h" in w["text"]
    )
    if not (qax and len(mh) >= 2):
        return None, None
    lo, hi = 95, mh[0] - 2

    def band(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return lo < np.mean(ys) < hi and max(xs) - min(xs) > 60 and max(ys) - min(ys) > 12

    strokes = [c["pts"] for c in page.curves if band(c["pts"])]
    return strokes, qax


def _multitec_page_strokes(page):
    words = page.extract_words()
    qax = mt_q_axis(words)
    mh = sorted((w["top"] + w["bottom"]) / 2 for w in words if w["text"] in ("m3/h", "m³/h"))
    if not (qax and len(mh) >= 2):
        return None, None
    lo, hi = 95, mh[0] - 3
    raw = [
        c["pts"]
        for c in page.curves
        if lo < np.mean([p[1] for p in c["pts"]]) < hi
        and max(p[0] for p in c["pts"]) - min(p[0] for p in c["pts"]) > 8
    ]
    qa, qb = qax
    x_left = -qb / qa
    stitched = [
        ch
        for ch in _stitch(raw)
        if max(p[0] for p in ch) - min(p[0] for p in ch) > 55
        and min(p[0] for p in ch) < x_left + 30
    ]
    return stitched, qax


def audit(pdf_path: str, yaml_path: Path, kind: str) -> list[dict]:
    by_page = _entries_by_page(yaml_path)
    pdf = pdfplumber.open(pdf_path)
    rows = []
    for page in pdf.pages:
        entries = by_page.get(page.page_number)
        if not entries:
            continue
        text = page.extract_text() or ""
        if kind == "omega":
            strokes, qax = _omega_page_strokes(page)
            labels = len({int(x) for x in OD_RE.findall(text)})
            name = (SIZE_RE.search(text) or [None, "?"])[1] if SIZE_RE.search(text) else "?"
        else:
            strokes, qax = _multitec_page_strokes(page)
            labels = len({int(x) for x in MT_OD.findall(text)})
            hm = MT_HEAD.search(text)
            name = f"Multitec {hm.group(1)}" if hm else "?"
        if not strokes or not qax:
            rows.append(
                {"kind": kind, "page": page.page_number, "name": name, "flags": "no strokes/axis"}
            )
            continue
        qa, qb = qax
        stroke_qmax = max((qa * max(p[0] for p in s) + qb) / 3.6 for s in strokes)
        dig_qmax = max(float(e["curve"]["q_lps"][-1]) for e in entries)

        flags = []
        if len(entries) < len(strokes):
            flags.append(f"dropped {len(strokes) - len(entries)} curve(s) ({len(strokes)} on page)")
        if labels and labels != len(entries):
            flags.append(f"{labels} o-labels vs {len(entries)} entries")
        cov = dig_qmax / stroke_qmax if stroke_qmax > 0 else 1.0
        if cov < 0.90:
            flags.append(f"truncated to {cov * 100:.0f}% of Qmax")
        rows.append(
            {
                "kind": kind,
                "page": page.page_number,
                "name": name,
                "entries": len(entries),
                "strokes": len(strokes),
                "o_labels": labels,
                "dig_qmax_lps": round(dig_qmax, 1),
                "stroke_qmax_lps": round(stroke_qmax, 1),
                "coverage": round(cov, 2),
                "flags": "; ".join(flags),
            }
        )
    return rows


def main():
    args = sys.argv[1:]
    om = _arg(args, "--omega-pdf", "KSB/dow-omega-data.pdf")
    mt = _arg(args, "--multitec-pdf", "KSB/dow-multitec-data.pdf")
    csv_out = _arg(args, "--csv", None)

    rows = audit(om, OMEGA_YAML, "omega") + audit(mt, MULTITEC_YAML, "multitec")
    flagged = [r for r in rows if r.get("flags")]
    flagged.sort(key=lambda r: (r["kind"], -r.get("coverage", 1.0), r["page"]))

    print(f"{len(rows)} datasheet pages audited, {len(flagged)} flagged\n")
    print(f"{'kind':<9}{'page':>5}  {'name':<18}{'ent':>4}{'strk':>5}{'lbl':>4}{'cov':>6}  flags")
    for r in flagged:
        print(
            f"{r['kind']:<9}{r['page']:>5}  {r.get('name', '?'):<18}"
            f"{r.get('entries', '-'):>4}{r.get('strokes', '-'):>5}{r.get('o_labels', '-'):>4}"
            f"{r.get('coverage', '-'):>6}  {r['flags']}"
        )
    if csv_out:
        cols = [
            "kind",
            "page",
            "name",
            "entries",
            "strokes",
            "o_labels",
            "dig_qmax_lps",
            "stroke_qmax_lps",
            "coverage",
            "flags",
        ]
        with open(csv_out, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {csv_out}")
    return 1 if flagged else 0


def _arg(args, name, default):
    return args[args.index(name) + 1] if name in args else default


if __name__ == "__main__":
    raise SystemExit(main())
