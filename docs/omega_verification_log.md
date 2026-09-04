---
title: KSB Omega verification log
---

# KSB Omega datasheet-verification log

A page-by-page review of `ksb_omega_50hz.yaml` against the printed datasheet,
using `tools/verify_ksb_omega.py <pdf> --pages …` (digitised H-Q polylines
overlaid on the rendered page + the digitised numbers).

Per page: **H-Q** = do the overlaid curves sit on the printed H-Q lines for
every impeller ø? **BEP** = is the digitised `(q_bep, eff_bep)` on the printed
efficiency island? **NPSHr** = does the digitised NPSHr trace match?

`verified: true` is set on an entry only when its H-Q overlay is clean, the
numbers match the printed axes, and `catalog-check` has no finding for it.
Issues are left `verified: false` and listed here for the digitiser backlog.

| pages | family | H-Q | BEP | NPSHr | notes |
|---|---|---|---|---|---|
| 8 | 080-210A 2900 | ✅ 4/4 | ✅ | ✅ | clean |
| 9 | 080-210B 2900 | ✅ 4/4 | ✅ | — | NPSHr for ø215 was a flat 16.1 m border line → dropped (commit f298b00); no NPSHr digitised for this page now |
| 10 | 080-270A 2900 | ✅ 4/4 | ⚠️ | ⚠️ | BEP x for ø235/ø215 lands past curve Qmax; NPSHr for ø255 tops 17.7 m (likely runout border) |
| 11 | 080-270B 2900 | ✅ 4/4 | ⚠️ | ⚠️ | ø235 BEP x ≈ Qmax; NPSHr for ø275 tops 18.1 m |
