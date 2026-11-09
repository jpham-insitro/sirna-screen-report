# sirna-screen-report

A Claude skill: end-to-end QC & knockdown report for siRNA screens (confluence + qPCR), with an
independent QC-verification gate. The installable bundle is `sirna-screen-report.skill` (a zip of the
`sirna-screen-report/` folder). The unpacked source is also committed under `sirna-screen-report/`.

## Contents
- `sirna-screen-report/SKILL.md` — the skill instructions (STEP 0–9 pipeline).
- `sirna-screen-report/assets/report_template.html` — canonical dark-theme MASTER report template.
- `sirna-screen-report/assets/interactive_tables.html` — 10-pt levers / 3-pt triage + simplified Q8 tables.
- `sirna-screen-report/assets/examples/` — reference figures (mimic targets) + README.
- `sirna-screen-report/scripts/` — resolver + confluence parsers + plate colors.
- `sirna-screen-report.skill` — the packaged, installable bundle.

## Install
Install `sirna-screen-report.skill` via Settings → Capabilities (or your Cowork/Claude Code plugin flow).
