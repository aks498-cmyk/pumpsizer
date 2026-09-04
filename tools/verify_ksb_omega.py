"""Spot-check the digitised KSB Omega head curves against the datasheet.

Renders datasheet pages and overlays the H-Q polylines the digitiser read for
each impeller diameter.  If the coloured points sit on the printed curves the
axis calibration and curve pick are right.

    py tools/verify_ksb_omega.py [path/to/dow-omega-data.pdf] [--pages 8,26,46,71]

With no ``--pages`` it rewrites the fixed 4-page ``docs/ksb_omega_verification.png``;
``--pages`` overlays any set (handy while checking a shortlisted pump against the
paper booklet) and writes ``docs/ksb_omega_pages_<n_n_...>.png``.

Needs: pdfplumber, matplotlib, numpy.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pdfplumber  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _verify_common import print_catalogue_rows  # noqa: E402
from digitise_ksb_omega import SIZE_RE, _q_axis, _value_axis  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs/ksb_omega_verification.png"
PAGES = [8, 26, 46, 71]
RES = 150
COLOURS = ("#e6194B", "#4363d8", "#3cb44b", "#f58231", "#911eb4")


def _head_curves(page):
    """The H-band curve polylines (page coords), biggest impeller first, plus a
    title - the same pick ``digitise_ksb_omega.digitise_page`` makes."""
    text = page.extract_text() or ""
    m = SIZE_RE.search(text)
    words = page.extract_words()
    qax = _q_axis(words)
    mh_rows = sorted(
        (w["top"] + w["bottom"]) / 2 for w in words if "m³/h" in w["text"] or "m3/h" in w["text"]
    )
    if not (m and qax and len(mh_rows) >= 2):
        return None, None
    h_band = (95, mh_rows[0] - 2)

    def in_band(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (
            h_band[0] < np.mean(ys) < h_band[1]
            and max(xs) - min(xs) > 60
            and max(ys) - min(ys) > 12
        )

    heads = [c["pts"] for c in page.curves if in_band(c["pts"])]
    heads.sort(key=lambda pts: min(pts, key=lambda p: p[0])[1])  # highest shut-off first
    h_ax = _value_axis(words, *h_band)
    tag = "" if h_ax else "  [H axis uncal]"
    return heads, f"Omega {m.group(1)}  {m.group(2)} rpm  (p.{page.page_number}){tag}"


def main():
    args = list(sys.argv[1:])
    pages, out = PAGES, OUT
    if "--pages" in args:
        i = args.index("--pages")
        pages = [int(x) for x in args.pop(i + 1).split(",")]
        args.pop(i)
        out = OUT.with_name("ksb_omega_pages_" + "_".join(map(str, pages)) + ".png")
    pdf_path = args[0] if args else "KSB/dow-omega-data.pdf"

    pdf = pdfplumber.open(pdf_path)
    scale = RES / 72.0
    ncol = 2 if len(pages) > 1 else 1
    nrow = math.ceil(len(pages) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(6.5 * ncol, 8.5 * nrow), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    for ax, pno in zip(axes.flat, pages):
        page = pdf.pages[pno - 1]
        heads, title = _head_curves(page)
        ax.imshow(page.to_image(resolution=RES).original)
        ax.set_title(title or f"p.{pno} (no curve found)", fontsize=10)
        for ch, colour in zip(heads or [], COLOURS):
            ax.plot(
                [p[0] * scale for p in ch],
                [p[1] * scale for p in ch],
                "o",
                ms=2.2,
                color=colour,
                alpha=0.85,
            )
    fig.suptitle(
        "KSB Omega - digitised H-Q polylines (per impeller ø) over the datasheet", fontsize=12
    )
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(out, dpi=110)
    print(f"wrote {out}")
    print_catalogue_rows("src/pumpsizer/data/catalog/ksb_omega_50hz.yaml", pages)


if __name__ == "__main__":
    main()
