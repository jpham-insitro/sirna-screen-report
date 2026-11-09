# Reference example figures (target style — "mimic as close as possible")

Source: user's "instructions to update" (2026-07). For any STEP 6 figure marked
**(mimic example)**, open the matching PNG here BEFORE coding and match its layout,
colors, annotations, ordering, and reference lines — on the report's dark theme.

| File | Figure | Key features to match |
|------|--------|-----------------------|
| fig3_workflow_summary.png | Fig 3 | Vertical flowchart; one full-width rounded box per work order (Order ID top-left italic, bold step title, `instrument \| start → end` detail), down-arrows between. PASTEL fill per step. Partial-plate note in box (e.g. T2 "6/12 plates"). |
| fig4_workorder_gantt.png | Fig 4 / Fig 4b | Per-work-order stacked panels; each = per-plate start-time timeline (colored dot + `N. <plate>`, staggered) on an HH:MM axis; panel title = WO name (accent) + grey `Order <id> · plate start times · span <N> min · cadence ~<x> min/plate`. Dark bg. Fig 4 = liquid-handling WOs; Fig 4b = T1/T2 imaging WOs. |
| fig4_gantt_workflow_imaging.png | (superseded) | OLD Fig 4 (WO bars + imaging markers). Replaced by fig3_workflow_summary + fig4_workorder_gantt. |
| fig5_t1_confluence_heatmaps.png | Fig 5 | Grid of 8×12 per-plate heatmaps, red YlOrRd 0–100, green PASS spine, title "PExxxx (PASS, %CV=…)", shared "Confluence %" colorbar. Seeding order. |
| fig7_t1_vs_t2_mean_confluence.png | Fig 7 | Bar = mean, whisker = ±SD, grey jittered dots = individual wells, value labels "mean ±SD", dashed 70% ref. (Report grouped T1 vs T2.) |
| fig8_cv_by_plate.png | Fig 8 | Green %CV bars + value labels, orange FLAG>20% + red FAIL>25% dashed lines, y→30; STATUS table beneath (PLATE/READ/MEAN/%CV/STATUS). |
| figQ3_housekeeping_cq.png | Q3 | Per-plate grouped strip scatter, dashed plate separators + plate-label boxes, ctrl first, colored by conc (grey ctrl / red 0.2 / blue 2 / green 20 nM), dashed Cq=25, legend. |
| figQ4_3pt_knockdown_bars.png | Q4 (3pt) | One subplot/plate; grouped bars per siRNA (20 amber / 2 purple / 0.2 blue), white replicate dots, SEM whiskers, green dashed benchmark 20 nM, status-colored subplot titles, figure-level legend. |
| figQ4_10pt_doseresponse_lines.png | Q4 (10pt) | One subplot/plate; LINE per siRNA + SMARTpool (grey dashed) of mRNA-remaining % vs dose (nM, log), SEM error bars, 50% orange dashed + 100% dotted refs. |
| figQ5_ranked_rna_remaining.png | Q5 | Grouped bars, ALL 3 doses per siRNA (0.2 nM teal #5eead4 / 2 nM blue #5dade2 / 20 nM amber #f5b041 "tox"), mean±SEM; RANKED on the non-toxic 0.2 nM dose (most potent left). Pooled controls block at right (dashed divider): SEMA3C pool (+) green-edged, mock (−) grey ≈100%, mean±SEM over all replicates/plates. Dotted = pooled benchmark @0.2 nM; solid red = 50%. NOT y-capped at 100 (bars exceed 100). 20 nM among often > 2 nM = 20 nM toxicity. (OLD 2-dose version kept as figQ5_ranked_rna_remaining.OLD-2dose.png.) |
| figQ6_potency_dotplot.png | Q6 | One row/siRNA (label + plate); teal line KD50 (●)→KD80 (◆); max-KD % at far left; "KD80 not reached" annotation; SMARTpool row; log dose x; legend; indicate direction (left = more potent). |
| figQ8_ranked_knockdown_table.png | Q8 | HTML table: SIRNA/PLATE/KD@20nM/@2nM/@0.2nM/MAX KD/KD50/CALL, sorted by KD@20nM; ★ benchmark row; CALL colored strong/moderate/weak/inactive; threshold footnote. |
| figQ9_perplate_scorecard.png | Q9 | Per-plate `.pcard` grid (Confluence T1 status/mean/%CV; qPCR status/siPPIB KD/HK Cq; one-line note; ACCEPT pill) + a "qPCR QC summary" table. |
