"""Spot-check the digitised KSB Multitec per-stage head curves.

Renders four datasheet pages and overlays the polyline the digitiser stitched
back together from the fragmented H-Q segments.  If the red points sit on the
printed per-stage head curve, the stitch + axis calibration is right.

Output: docs/ksb_multitec_verification.png

    py tools/verify_ksb_multitec.py [path/to/dow-multitec-data.pdf]

Needs: pdfplumber, matplotlib, numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pdfplumber  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from digitise_ksb_multitec import HEAD, _q_axis, _stitch  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs/ksb_multitec_verification.png"
PAGES = [14, 22, 46, 52]  # 50/3.1 2900, 100/7.1 2900, 65/6.1 1450, 125/9.1 1450
RES = 150


def _h_curves(page):
    """Re-run the digitiser's H-band stitch for one page -> list of polylines
    (page coords) plus the heading string."""
    words = page.extract_words()
    text = page.extract_text() or ""
    hm = HEAD.search(text)
    qax = _q_axis(words)
    m3h_rows = sorted((w["top"] + w["bottom"]) / 2 for w in words if w["text"] in ("m3/h", "m³/h"))
    if not (hm and qax and len(m3h_rows) >= 2):
        return None, None
    qa, qb = qax
    x_left = -qb / qa
    h_band = (95, m3h_rows[0] - 3)

    def in_band(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return h_band[0] < np.mean(ys) < h_band[1] and max(xs) - min(xs) > 8

    def usable(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return max(xs) - min(xs) > 55 and max(ys) - min(ys) > 10 and min(xs) < x_left + 30

    segs = [c["pts"] for c in page.curves if in_band(c["pts"])]
    chains = sorted(
        (ch for ch in _stitch(segs) if usable(ch)),
        key=lambda pts: min(pts, key=lambda p: p[0])[1],
    )[:2]
    hyd = next(
        (
            w["text"]
            for w in words
            if w["top"] < 100 and w["text"][:1].isdigit() and "." in w["text"]
        ),
        "?",
    )
    rpm = 2900 if "2900" in text else (1450 if "1450" in text else "?")
    return chains, f"Multitec {hm.group(1)}/{hyd}  {rpm} rpm  (p.{page.page_number})"


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "KSB/dow-multitec-data.pdf"
    pdf = pdfplumber.open(pdf_path)
    scale = RES / 72.0
    fig, axes = plt.subplots(2, 2, figsize=(13, 15))
    for ax, pno in zip(axes.flat, PAGES):
        page = pdf.pages[pno - 1]
        chains, title = _h_curves(page)
        im = page.to_image(resolution=RES).original
        ax.imshow(im)
        ax.set_title(title or f"p.{pno} (no curve found)", fontsize=10)
        ax.axis("off")
        for ch, colour in zip(chains or [], ("#e6194B", "#4363d8")):
            xs = [p[0] * scale for p in ch]
            ys = [p[1] * scale for p in ch]
            ax.plot(xs, ys, "o", ms=2.4, color=colour, alpha=0.85)
    fig.suptitle(
        "KSB Multitec - digitised per-stage H-Q polyline (stitched) over the datasheet",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(OUT, dpi=110)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
