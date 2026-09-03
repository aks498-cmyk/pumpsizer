# Turning a KSB (or similar) curve booklet into a catalogue

`src/pumpsizer/data/catalog/ksb_omega_50hz.yaml` was generated from
`dow-omega-data.pdf` (KSB *Omega / Omega V 50 Hz Characteristic Curves
Booklet*, 15.02.2016).  The PDF is a set of **plotted curves** - only the axis
ranges, page numbers, speeds and impeller-diameter labels are machine-readable,
so each of the 74 entries is:

* `envelope_only: true` - no digitised `curve:` block yet;
* `q_min_lps` / `q_max_lps` / `shutoff_head_m` - **read from the page's axis
  ticks** (real);
* `q_bep_lps` / `h_bep_m` - **approximated** (`q_bep ~= 0.6 * q_max`,
  `h_bep ~= 0.72 * shutoff head`), hence `estimated_bep: true` and
  `verified: false`;
* `datasheet_page` - the exact booklet page with the full curve.

The selection engine uses these for a **shortlist only** and every candidate
carries a "confirm curve from ... booklet p.N" note plus a score penalty
(x0.88) so a verified pump always outranks an estimate at equal merit.

## Making an entry design-quality

1. Open the booklet page in `datasheet_page`.
2. Read 6-9 `(Q, H)` points off the curve **for the impeller diameter you
   intend to use** (largest is fine; include Q = 0 and a point near `Qmax`).
3. Read efficiency % and NPSH3 (m) at the same flows.
4. In the YAML entry, add a `curve:` block and delete the estimate flags:

   ```yaml
   - manufacturer: KSB
     series: Omega
     model: 350-360B (1450rpm)
     reference_speed_rpm: 1450
     poles: 4
     impeller_diameter_mm: 360
     min_impeller_diameter_mm: 300      # from the page's smallest oNNN label
     datasheet_page: 76
     verified: true                     # <- after a second check
     source: "KSB Omega 50 Hz booklet p.76, impeller B"
     curve:
       q_lps:   [0, 120, 240, 300, 360, 450]
       h_m:     [ .,   .,   .,   .,   .,   . ]
       eff_pct: [ .,   .,   .,   .,   .,   . ]
       npshr_m: [ .,   .,   .,   .,   .,   . ]
   ```

   (`envelope_only`, `estimated_bep`, `q_bep_lps`, `h_bep_m`, `shutoff_head_m`
   are then ignored.)

## Regenerating the envelope file

`tools/build_ksb_omega_catalog.py` re-parses the PDF.  Re-run it if you get an
updated booklet; then hand-upgrade the entries you actually use.
