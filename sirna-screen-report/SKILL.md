---
name: sirna-screen-report
description: >-
  End-to-end report for siRNA screens. The report includes summary, plate map, screen details,
  workflow overview, imaging QC heatmap, bar chart, and summary for each plate ID, sampling
  images, identification of outliers, and analysis of qPCR results (dose-response, KD50/KD80
  potency, housekeeping QC).
---

# siRNA Screen QC Report

End-to-end QC agent for siRNA screens run on the Bamboo/Herb workcell. Produces a dark-themed HTML QC report for either or both readouts:

- **Confluence** (SparkCyto): plate layout, assay parameters, workflow diagram, Gantt chart, T1/T2 confluence heatmaps, mean confluence, %CV, QC status cards, and root-cause analysis for flagged plates.
- **qPCR knockdown** (QuantStudio): per-plate knockdown (2^-ddCt / RNA-remaining %), Cq and housekeeping QC, %CV, dose-response, 4-PL potency (KD50/KD80/max KD vs a pooled benchmark), and outlier removal.

**Output = a single "MASTER" report** (named `<screen>_<celltype>_<DRC>_<N>plates_<seeddate>.html`,
e.g. `MASH3_3T3_3pt_6plates_2026Jul8.html`; see STEP 7) that merges every readout that was
run into one dark-themed document with a TOC, executive summary + KPI cards, "How to read" guide
boxes, per-plate verdict cards, a structured repeat-decision, and a provenance footer. It is built
from `assets/report_template.html` (the canonical design system) — see STEP 7. When it supersedes
earlier standalone reports, it says so and keeps them for reference.

Supports three assay designs on 96-well plates:

| Design | Compounds/plate | Doses/compound | Fig 1 style |
|--------|----------------|----------------|-------------|
| **Single-dose arrayed** | Many (one siRNA per well group) | 1 | Light bg, rectangles, color by well_type |
| **3-pt DRC** | 6 | 3 (20 / 2 / 0.2 nM) | Dark bg, circles, 3-shade gradient per compound |
| **10-pt DRC** | 2 | 10 (serial dilution) | Dark bg, circles, 10-shade gradient per compound |

> **Dose count vs name:** the collection/screen *name* (e.g. "10-pt") may not equal the number of
> *populated* dose columns. Read the actual dose count from the plate map — one "10-pt" screen had
> **9** filled dose columns (20 → 0.0006 nM, ~4-fold). Never hardcode the dose count from the name.

---

## Execution environment (READ FIRST — pick your path)

This skill runs in one of two environments. Detect which you are in *before* STEP 1, because
STEP 1, 2, 4 and 8 differ.

**A. Native Jupyter kernel** (insitro infra; `mcp__jupyter__*` tools present). The default the
step-by-step below assumes: `PlateMetadataLoader`, in-kernel `matplotlib`, and `boto3`/`aws s3`
with AWS creds all work. Use kernel paths as written.

**B. Cowork / MCP-only** (no Jupyter kernel; a sandbox shell with **no** `aws`/`boto3`/creds).
Verify by checking for a kernel tool and testing `python3 -c "import boto3"` in the sandbox — if
either fails, you are in mode B. In mode B:
- **Input resolution (STEP 0A) & metadata (STEP 2):** resolve from the `insitro-index` search
  tools (+ Groot / Benchling DWH) via MCP. See STEP 0 and STEP 2 "Mode B".
- **Confluence (STEP 4):** the XML is text but ~100 KB/plate and **exceeds `read_s3_file`'s
  token cap** — use the size-cap workaround in STEP 4 "Mode B".
- **qPCR (STEP 4Q):** pull Cq / ddCt / knockdown from the `qpcr_well_measurements` index — no raw parse
  needed. **Raw source of record = the native QuantStudio `.eds`** run file, pulled **by plate ID in the
  filename** from `s3://insitro-lab-equipment/fungen_qPCR_output/` (binary ZIP — needs a raw-bytes
  download + unzip, not `read_s3_file`); a Result **CSV** export, if present, parses equivalently.
- **Figures (STEP 6):** generate PNGs with `matplotlib` in the sandbox shell
  (`pip install --break-system-packages matplotlib numpy pandas`), then base64-embed into the HTML
  (STEP 7). No notebook/`nbconvert` needed.
- **Well images (STEP 8):** no kernel; use `download_s3_prefix` (raw bytes) instead of `aws s3 cp`.
- Everything else (Athena log queries, S3 text/list, QC math, thresholds) is identical.

Both modes produce the same deliverable: a dark-themed HTML QC report + data CSVs in SAVE_DIR.

---

## Key gotchas (read before writing any code)

| Issue | Fix |
|-------|-----|
| well_type='mock' for INS compounds (DRC screens) | Color Fig 1 by compound_name, not well_type |
| well_row is int 1-8, not letter | row_idx = int(well_row) - 1; y = 7 - row_idx |
| well_column in confluence_data is int64 | Compare with int, not str |
| SparkCyto image filename well ID | fname.split('_')[3], not [4] |
| S3 paginator truncates at 1000 prefixes | Mode A: `aws s3 ls` in the kernel. Mode B: `list_s3_objects` with a **narrow prefix** (e.g. down to the minute/method) so you stay under the cap. |
| PlateMetadataLoader times out in execute_code | Run via subprocess.Popen from kernel |
| get_well_properties_augmented_with_compounds() crashes | Use df_properties + df_compounds manually |
| reagent_concentration_value is Categorical dtype | pd.to_numeric(..., errors='coerce') before validate |
| Relative paths in plt.savefig() | Always use absolute SAVE_DIR paths |
| f-string backslash in Python 3.11 | Pre-extract dict values to variables before f-strings |
| Gantt WO labels overlapping | Put labels in y-axis ticks, not inside bars |
| Plate order in figures | Use seeding/imaging timestamps, not plate ID numbers |
| Fig 1 layout unknown | Always read reference *platemap.png before coding |
| **"PRJ###" is NOT `project_code`** | In the `projects` index, `PRJ###` is the `id`/`benchling_id`; the `project_code` field is a *different* short code (e.g. `2004`). Match a PRJ token on `id`, never `project_code`. |
| **Plate→project link is free-text** | Neither the `plates` nor `qpcr_well_measurements` index has a numeric project field — the PRJ code is embedded in `experiments[].name` / `experiment.name` (`"EINS##### - PRJ### - <desc>"`). Parse it with a regex; confirm before trusting a full-text match. |
| Ambiguous project name | A name query can match >1 project. Never guess — list candidates and ask (STEP 0). |
| MCP `read_s3_file` is UTF-8 text only | Binary (XLSX/parquet/.db/**JPG/TIFF**) errors out on the first non-UTF-8 byte. For text, use the XML route (STEP 4). For binary **bytes** (well images, STEP 8) use `download_s3_prefix` (mode B) or `boto3`/`aws s3` inside the kernel (mode A). |
| MCP `read_s3_file` **token/size cap** | The confluence XML is ~100 KB/plate and **exceeds the tool's max-token cap** — the call errors and saves the payload to a host temp file. It is NOT returnable inline. See STEP 4 "Mode B" for the host-file/subagent parse (or use `download_s3_prefix`). |
| `search_index` output can blow the token cap | `plates`/`projects`/`qpcr_well_measurements` docs are large. Query with a tight `query`/`size`, and if a call errors to a host temp file, parse it with a **subagent** (jq/python), not the Read tool. |
| **Barcode is NOT inside the confluence XML** | Well tokens are generic (`_96PE_<row><col>_`); plate identity rides only on the S3 **folder name**. When parsing plates in parallel, key each parse explicitly to its folder→barcode, and run the STEP 5 integrity check (no two plates may share an identical confluence vector) to catch file mix-ups. |
| **Barcode IS inside the qPCR index** | `qpcr_well_measurements.source_plate_id` carries the plate barcode directly — key qPCR parses on it (contrast with the confluence XML above). |
| **Raw qPCR `.eds` = binary ZIP, by plate ID** | Raw qPCR lives in `s3://insitro-lab-equipment/fungen_qPCR_output/` as QuantStudio `.eds` files; find the file by the **plate barcode(s) in its name** (one `.eds` = up to four 96-well plates as one 384-well run). It is a ZIP — pull raw bytes (`download_s3_prefix` / `boto3`), **unzip**, and read the SDS members; `read_s3_file` (UTF-8) fails on it. Then the standard 384→96 + ΔΔCt pipeline. See STEP 4Q. |
| **Summary must be readout-complete** | If a qPCR section (§5 knockdown/potency, §5.1 %CV, §6 outlier removal) is emitted, the §1 executive summary + KPI cards MUST reflect it (knockdown, KD50/KD80 potency, housekeeping QC, cleanup). Never ship a confluence-only summary when qPCR also ran — the top summary and the body must agree. |
| SparkCyto folder timestamp drift | The workspace-folder second can differ from the Cellario read-launch second by ~1 s. Match by **minute prefix + barcode suffix**, not exact-second. |
| No warehouse confluence table | There is no queryable DB table of SparkCyto confluence. The XML export is authoritative. |
| No `aws` CLI / boto3 / Athena creds in **sandbox bash** | Route S3/Athena work through MCP tools. The Jupyter kernel is a separate environment that *does* have `aws`/`boto3`. |
| SparkCyto folder name | `<Method>_<localTS>_<barcode>` -- barcode is a **suffix**, timestamp is **local (UTC-7)**, log timestamp is **UTC**. Convert before matching. |
| XML has no "Confluence" field | Compute % from `TotalAreaInUm2` / well area. 6.4 mm-bottom 96-well = **3.217e7 µm²**. |
| Partial T2 | Not all plates are imaged at Day2 -- join on available reads, note missing plates in Fig 6. |
| No pyarrow in sandbox | Write **CSV** as the source of truth; parquet may not round-trip. |
| Confluence read events | Live in `Cellario_Drivers.log` (Driver.Spark lines), **not** `_Diagnostic.log`. |
| Dark-theme figure colors | Use bright, high-contrast series vs the dark bg — **avoid dark-navy fills, they vanish**. Good pairs: bright blue `#5dade2` + amber `#f5b041` (two-series bars); grey/red/blue/green (categorical dots). Bump dot size and axis-label font on dense plots. |
| Knockdown / RNA-remaining axes | Cap y at **0–100%** unless data genuinely exceeds it — don't let autoscale run to 160. |
| Per-compound figure x-axis | Label with the **full sample registry ID** (`INS-#####-01`), never `#01/#02` shorthand. Rotate 90° if long; keep legends **outside** the panels (a per-panel legend overlaps bars). |
| matplotlib timeline / Gantt bar width | With `left=mdates.date2num(...)`, `barh` width must be in **DAYS** (`(end-start).total_seconds()/86400`), not hours — else short steps render absurdly wide. |

---

## Companion skills (invoke when context calls for it)

This skill delegates to three companion skills instead of re-implementing their lookups. **Invoke them
via the Skill tool** whenever the trigger below is met — either because the user's prompt asks for it
or because a step needs the information. Fold the returned result back into the report; cite it in
Provenance. If a companion skill is unavailable in the session, fall back to the raw MCP tools noted.

| Companion skill | Invoke when… | Feeds |
|-----------------|-------------|-------|
| **`/lims:entity-lookup`** | you have an entity *name* and need its registry ID / type / Benchling URL — a compound or siRNA common name (e.g. "ON-TARGETplus Mouse Fam13a"), a cell line (e.g. "A549", "3T3-L1"), a reagent, or a target-gene entity; or the user asks "what is the registry ID for X". | STEP 0B target/cell-line resolution; STEP 2 well_type + compound identity; Fig 2 / §5 method card; Provenance IDs. Fallback: `insitro-index search_all` / `entity-lookup` index. |
| **`/experimental-planning:find-related-benchling-entries`** | you need prior related runs for context — same campaign/CACT, same cell line, or same process/instrument — e.g. to find the **standalone reports this master supersedes**, historical knockdown/confluence baselines, or expected timings/volumes; or the user asks "what other runs are related / has this been done before". | STEP 0B batch/context; §1 executive-summary framing; §6/§8 "consistent with prior runs?"; the "supersedes standalone reports" header line. Fallback: `insitro-index` notebooks/experiments search. |
| **`/lims:view-plate-maps`** | you need the contents of a plate or collection — per-well entity, concentration, role/well_type, dose scheme — or need to find the collection(s) for an experiment (EINS→collection), or the user names a plate barcode / collection and asks "what's in it". | STEP 0A layout resolution; **STEP 2 plate metadata (primary path in Mode B)**; Fig 1 plate map; dose-count confirmation. Fallback: Groot `get_plate_map_collection` / `list_plate_map_collections`. |

Prefer the companion skill over ad-hoc queries when its trigger fits — it returns normalized output and
keeps this skill's steps thin. Do not invoke one that is already running.

---

## STEP 0 -- Choose data operation (ASK FIRST)

**Before resolving inputs or running anything else, ask the user WHICH data operation they want.**
In Cowork, present these as an `AskUserQuestion` single-select (allow multi-select); otherwise list
them and wait for a choice. Do not assume the full report.

**Workflow glossary** (Bamboo/Herb/CellFI workcell work orders):

| WF | Name | What it is |
|----|------|-----------|
| **WF1** | siRNA Dilution & Shake | siRNA plate dilution series + shake |
| **WF2** | Transfect and Seed | lipoplex formation, transfection, cell seeding |
| **WF3** | Feed | media feed / exchange |

**Options:**

| # | Operation | Runs | Scope |
|---|-----------|------|-------|
| 1 | Pull run logs for **WF1 & WF2**, plot by plate ID | STEP 0A → STEP 3 (filter WF1+WF2) → STEP 6 run-log view | Instrument run logs (timings / events / errors) for the dilution + transfect workflows, plotted per plate |
| 2 | Pull run logs for **WF1, WF2 & WF3**, plot by plate ID | STEP 0A → STEP 3 (filter WF1+WF2+WF3) → STEP 6 run-log view | As #1 plus the Feed workflow |
| 3 | Pull run logs **and/or confluence data** | STEP 0A → STEP 3 → STEP 4 → STEP 5 → STEP 6 (Figs 1-10) | Full confluence QC path; ask whether logs-only or logs + confluence |
| 4 | Pull run **sampling images** | STEP 0A → STEP 3 → STEP 8 | SparkCyto well / sampling images for the plates |
| 5 | Pull **qPCR data** | STEP 0A → STEP 4Q → STEP 5 (qPCR) → STEP 6 (Figs Q1-Q5) | qPCR Cq / ddCt / knockdown report |

**After the user picks**, set `DATA_OP`, then ALWAYS run **STEP 0A** to resolve the plate set (every
option needs it). Run only the steps listed for the chosen option; skip the rest. If more than one
option is selected (e.g. "3 and 5"), run the union of their steps.

**WF filtering (options 1 & 2).** WF1/WF2/WF3 are workcell work orders whose exact protocol/method
strings vary by run. Resolve the real names at runtime from the Cellario logs (STEP 3) or the Groot
work orders by matching the human names above (body/protocol containing "Dilution"/"Shake",
"Transfect"/"Seed", "Feed"). **Confirm the matched work-order names back to the user before plotting;
do NOT hardcode protocol strings into the skill.**

**Plot data by plate ID (options 1 & 2).** Produce a per-plate run-log view: for each plate, a
timeline / Gantt of the selected WF work-order events (start, end, duration, errors) keyed on plate
ID, plus a summary table (plate × WF: start, end, duration, error count). Order plates by their first
WF1 timestamp. Reuse the STEP 4 Gantt / STEP 6 figure machinery.

---

## STEP 0A -- Resolve inputs (project ID / project name / plate ID) → screen

**The screen can be identified three ways. Accept whichever the user gives, normalize to a plate
set, then continue.** Use `scripts/resolve_screen_inputs.py` as the spec for the field names,
matching rules, and dedup logic below (it also encodes the "PRJ ≠ project_code" and "plate→project
is free-text" gotchas so they can't be reintroduced).

**Classify the input:**
- matches `PRJ\d+` → **project code** (e.g. `PRJ087`)
- matches `P[A-Z]\d{4,}` → **plate ID** (e.g. `PE4002160`); one or many
- anything else → **project name** (free text, e.g. `Adiposity Discovery`)

**Resolution chains (insitro-index MCP `search_index`; Mode B). In Mode A use the kernel's index
client or the Benchling DWH equivalents.**

1. **Plate ID(s)** — most direct:
   - `search_index("plates", query=<barcode>)` → keep the doc whose `barcode`/`barcode_raw`
     equals the input. Read `experiments[0].name` (embeds `EINS#####` + `PRJ###`),
     `experiments[0].project` (project name), and `cell_line_instances[0]` (cell line + `Cins####`).
   - Parse `PRJ###` and `EINS#####` from the experiment name with a regex.

2. **Project code (`PRJ###`)**:
   - `search_index("projects", query="PRJ###")` → match on `id`/`benchling_id` **(NOT
     `project_code`)**. Read `name`, `experiments[]`, `campaigns[]` (→ `CACT###`).
   - Get the plate set: union of (a) `search_index("plates", query="PRJ###")` filtered to docs whose
     `experiments[].name` carries that PRJ, and (b) `search_index("qpcr_well_measurements",
     query="PRJ###")` deduped on `source_plate_id`. The union ensures confluence-only plates and
     qPCR plates are both captured.

3. **Project name** (free text):
   - `search_index("projects", query=<name>)` → fuzzy-match on `name`. **If more than one project
     matches, STOP and ask the user to choose** (list `id :: name` candidates) — do not guess.
   - Once a single project is chosen, resolve its plate set exactly as in (2).

**Choose the readout(s).** After resolving the plate set, determine which readouts exist:
- **qPCR available** if any plate returns rows from `qpcr_well_measurements`
  (`source_plate_id` match). See STEP 4Q.
- **Confluence available** if SparkCyto archives exist for the plates (STEP 3/4).
- If the user asked for a specific readout, honor it; otherwise run whichever exist and say so.
  If a requested readout is missing for some plates, list those plates as a gap — don't fail silently.

List the resolved values back — **project code, project name, plate set, cell line, campaign,
detected readout(s)** — and wait for confirmation before proceeding.

---

## STEP 0B -- Session setup (auto-resolve the rest, then confirm gaps)

**Do NOT ask the user for all fields up front.** With the plate set resolved in STEP 0, most
metadata is derivable. Resolve first, then show what you found and ask only for gaps.

**Auto-resolve** (Groot plate-map collection + Benchling DWH + insitro-index; see STEP 2 "Mode B";
delegate to the companion skills where they fit — `/lims:view-plate-maps` for layout,
`/experimental-planning:find-related-benchling-entries` for batch/context and superseded standalone
reports, `/lims:entity-lookup` for entity IDs):
- Project ID (`EINS##### - PRJ###`) and Campaign ID (`CACT### - PRJ###`)
- Cell line (registry / Cins ID)
- The 96-well layout: control roles, dose scheme + **actual dose count**, per-plate test-siRNA identities
- Instrument, screen dates (seed/transfect + image/qPCR reads)
- Batch structure (whether the plate set splits into replicate batches)

**Ask the user only for what you could not resolve or that is genuinely ambiguous**, e.g.:
- **Target gene** — often NOT in the registry (for qPCR the target IS in the index as `target_gene`;
  for confluence-only screens it may need to be asked). Do not guess. To resolve a compound/siRNA/cell-
  line *name* to its registry ID + Benchling URL, invoke **`/lims:entity-lookup`**.
- **Assay design** — infer from the dose scheme if possible, else confirm.
- **SAVE_DIR** — default to the connected project folder; confirm.
- **Timepoint / readout scope** — confluence T1-only vs T1+T2 (STEP 5); qPCR present or pending.
- **Reference platemap image** — check the project folder for a `*platemap.png`.

Keep Project ID and Campaign ID as **separate labeled fields**, each using a ` - ` separator between
the EINS/CACT number and the PRJ number — do not merge them or use `/`. Carry both through to Fig 2.

If the run is split into replicate batches, group and label **Figs 5-10 and the QC table by batch**.

---

## STEP 1 -- Notebook setup

**Mode B (Cowork / no kernel):** skip. Compute in the sandbox shell, write figures with `matplotlib`
(STEP 6, mode B). Create SAVE_DIR and optionally a short `README`/session-notes markdown file.

**Mode A (Jupyter kernel):**
1. `mcp__jupyter__list_kernels` → Core (CPU) kernel ID.
2. Connect with `mcp__jupyter__use_notebook` in connect mode using the Core kernel.
3. Verify kernel: `import sys; print(sys.executable)` — must show `/opt/envs/core/latest/...`.
4. Write setup cell with standard imports and SAVE_DIR.
5. Write a README markdown cell (reuse the extended HTS QC template if present).

---

## STEP 2 -- Plate metadata

### Mode A (kernel): PlateMetadataLoader
Critical: PlateMetadataLoader called via execute_code times out. Run via subprocess.Popen from inside the kernel.
1. Run PlateMetadataLoader via subprocess.Popen.
2. Extract df_properties and df_compounds manually; do not call get_well_properties_augmented_with_compounds().
3. Build well_type (see below). 4. Coerce reagent_concentration_value with pd.to_numeric(..., errors='coerce').
5. Save wells_metadata.parquet and wells_metadata.csv to SAVE_DIR.

### Mode B (Cowork / MCP-only): Groot + Benchling DWH + index
No PlateMetadataLoader. Resolve the same information via MCP tools:
1. Plate-map **collection** — **prefer `/lims:view-plate-maps`** (invoke it with the plate barcodes or
   the EINS→collection) for normalized per-well entity, concentration, role, and per-plate test-siRNA
   identities. Fallback: `list_plate_map_collections` / `get_plate_map_collection` (or
   `query_groot_db`) keyed on the barcodes.
2. Project/campaign/cell line: already resolved in STEP 0 (index) — cross-check with
   `query_benchling_dwh` if needed (`experiment$raw.project`, `plate$raw.barcode`).
3. Build well_type (see below). Coerce concentrations with `pd.to_numeric(..., errors='coerce')`.
4. Save `wells_metadata.csv` to SAVE_DIR (CSV only).

### Deriving well_type (both modes) — do NOT hardcode which control is "positive"
Read control roles from the **plate-map annotations**, not a fixed gene assumption:
- The dilution-series positive control may be a target SmartPool (e.g. **SEMA3C**), NOT siPPIB.
- **siPPIB** is often the single-dose transfection/assay control — not the dilution positive control.
- QC enum: `sample` = test-siRNA wells; `positive_ctrl` = annotated positive/benchmark control;
  `assay_ctrl` = single-dose transfection control (e.g. siPPIB); `mock`/`empty` = no compound.
- INS-XXXXXX test compounds may be labeled `mock` in Benchling — correct using compound_name.
- If plate-map annotations and a legacy assumption disagree, **trust the plate map** and note it.
Capture the **actual dose count** from the map (may be < the name's "N-pt").

---

## STEP 3 -- Cellario run logs (workflow events + SparkCyto reads)   [run-log & confluence readouts]

Used by DATA_OP options 1-4. Pull the workcell run logs via the **`query-lab-logs`** skill (Athena
query against `lab_logs.raw_logs_curated`); pass instrument host + date range, then parse.
- Filter `host_name` = instrument (Bamboo=`HR-CELLARIO-02`, Herb=`HR-CELLARIO-01`,
  CellFI=`HR-CELLARIO-03`), `date` BETWEEN screen_start-1 and screen_end+1.

**Options 1 & 2 (WF run logs by plate):** pull the **work-order / protocol lines** for the selected
workflows (WF1 siRNA Dilution & Shake, WF2 Transfect and Seed, WF3 Feed). Resolve each WF's real
work-order/protocol string at runtime (match body/protocol on "Dilution"/"Shake", "Transfect"/"Seed",
"Feed") and confirm the matches to the user. Extract per plate × WF: work-order name, start/end UTC,
duration, and any error/warning lines. Save `run_log_events.csv` (plate_id, wf, work_order, start_utc,
end_utc, duration_s, error_count) → SAVE_DIR; plot in STEP 6 (run-log view).

**Options 3 & 4 (confluence / images):** the SparkCyto read events live in **`Cellario_Drivers.log`**,
NOT `Cellario_Diagnostic.log`:
- `log_file_path LIKE '%Cellario_Drivers%'` and `body LIKE '%Driver.Spark%'`.
Per plate, extract the **Read command line** (barcode, method, read start UTC) and the
**completion line** (`RESULTDATA ... UncPath ... AutomationInterfaceExport.xml`). Timepoint from the
method/date (Day0→T1, Day2→T2). **Not every plate gets a T2 read.**
Extract: order_timeline.csv, imaging_timestamps.csv, seeding_order.csv → SAVE_DIR.
**Also (for the standard Fig 4b processing-order timelines):** pull the per-plate start times of the
two liquid-handling workflows — WF1 dilute-and-shake and WF2 seed-and-transfect — from the Cellario
Diagnostic log (per-plate first-touch timestamp within each order), and save them (e.g. append to
`run_log_events.csv` or a `processing_order.csv`: plate_id, wf, start_utc, rank). This runs on the
confluence path too, not only the run-log operation.

---

## STEP 4 -- Confluence extraction (XML, not XLSX)   [confluence readout only]

*(unchanged — read the XML export as text; skip the binary XLSX)*

1. **Locate the S3 archive folder** per plate:
   `s3://insitro-microscopy-spark-cyto-archive/<READER_HOST>/<Method>_<localYYYYMMDD_HHMMSS>_<barcode>/`
   - `<READER_HOST>` is the SparkCyto reader (Bamboo → `TE-SPARKCYTO-04`). Confirm from STEP 3 UncPath.
   - Barcode is a **suffix**; folder timestamp is **local (UTC-7)**, log timestamp is **UTC** (subtract 7 h).
   - Match by **minute prefix + barcode suffix**, not exact-second.
2. **Read** `Export/xml/AutomationInterfaceExport.xml`.
   - Mode A: read/parse in the kernel (or `boto3`).
   - Mode B: `read_s3_file` errors (exceeds token cap) → use `download_s3_prefix` on the plate's
     `Export/xml/` prefix, or a **subagent** that parses and writes one small `confluence_<barcode>.csv`
     per plate. Key each parse to its folder/barcode (barcode is NOT in the XML) and verify with STEP 5.
3. **Parse each `<ResultContext>`** with `scripts/parse_confluence_xml.py`: well from `_96PE_<row><col>_`
   token; scalar `TotalAreaInUm2`. There is no literal "Confluence" scalar.
4. **Confluence %** = `TotalAreaInUm2 / well_area * 100`; `well_area` (6.4 mm bottom 96-well) = **3.217e7 µm²**.
   %CV is independent of the denominator; state the denominator in the report.
5. **Save** `confluence_data.csv` (plate_id, well_row 1-8, well_column 1-12, well_label, timepoint,
   total_area_um2, confluence_pct). CSV is the source of truth.

**XLSX fallback** (only if XML unavailable AND binary reads work): `scripts/parse_confluence.py`
(FIM sheet = 2nd tab; anchor on a col-A cell **ending in** `Confluence [%]`).

---

## STEP 4Q -- qPCR extraction (index-first)   [qPCR readout only]

**Preferred path — pull pre-computed qPCR from the `qpcr_well_measurements` index. No CSV parse
needed.** Each document is one source well × plate and already carries the full knockdown pipeline
the legacy notebook computed by hand.

1. **Query per plate:** `search_index("qpcr_well_measurements", query=<barcode>)`, keep rows where
   `source_plate_id == <barcode>`. Paginate if `has_more`. (These docs are large — use tight `size`
   and, if a call errors to a host temp file, parse it with a subagent.)
2. **Fields to keep per well** (verified schema):
   - `source_plate_id`, `source_well_id` (e.g. `A2`), `qpcr_well_id` / `well_position` (384-well A1..P24)
   - `target_gene`, `housekeeping_gene`, and `qpcr_well_measurement_per_gene[]` with per-reporter
     `cq`, `cq_mean`, `cq_sd`, `reporter` (FAM=target, VIC=housekeeping), `amp_status`, `cq_confidence`,
     `omit`, `well_position`
   - `delta_ct`, `control_avg_delta_ct`, `delta_delta_ct`, `fold_change`, `mrna_remaining`,
     `knockdown_pct` (all pre-computed)
   - flags: `is_negative_control`, `is_positive_control`, `is_assay_control`, `is_control_annotated`,
     `control_source_well_ids`
   - `compounds[]` (`name` INS-####, `common_name`, `concentration_nm`), `cell_line_instances[]`,
     `experiment.name` (EINS/PRJ), `qpcr_run` (`s3_bucket`/`s3_key` raw CSV, `processed_exports`, and
     the **qPCR equipment for the sub-title**: `instrument_type` e.g. "QuantStudio 7 Pro System",
     `instrument_serial_number`, `block_type` e.g. "384-Well Block" → build `QPCR_INSTRUMENT` =
     "QuantStudio 7 Pro (SN <serial>, 384-well block)" for the header `.meta` and Provenance)
3. **Save** `qpcr_data.csv` (long: plate_id, source_well, target_gene, housekeeping_gene, cq_target,
   cq_hk, delta_ct, delta_delta_ct, fold_change, knockdown_pct, compound, concentration_nm, well_type).
   CSV is the source of truth.

**Trust-but-verify.** The index gives `knockdown_pct` / `mrna_remaining` directly, but the ddCt
baseline (`control_avg_delta_ct`) depends on which wells were treated as untreated controls
(`control_source_well_ids`). Spot-check a few wells: `delta_ct = cq_target - cq_hk`,
`ddCt = delta_ct - control_avg_delta_ct`, `RNAremaining% = 2^(-ddCt) * 100`. If the control set looks
wrong (e.g. excluded edge wells differ from the plate map), recompute from raw and note it.

**Raw `.eds` source — the canonical raw source of record; pull by plate ID from
`s3://insitro-lab-equipment/fungen_qPCR_output/`.** Whenever you must compute qPCR from scratch — the
index has no rows, the control set is disputed, or you're verifying — read the QuantStudio native run
file directly from this prefix (this is where the fungen qPCR runs land):
1. **Locate by plate ID.** `list_s3_objects` on `s3://insitro-lab-equipment/fungen_qPCR_output/` and pick
   the object whose **filename contains the plate barcode(s)** — verified pattern:
   `<date>_<op>_prod_results_<probes>_plates_<PE…>_<PE…>…_<YYYYMMDD_HHMMSS>.eds` (e.g.
   `…_plates_PE4002256_PE4002257_PE4002258_PE4002259_20260713_133638.eds`). **Take the `.eds` run file —
   NOT the same-named `.edt` template, and skip `_Copy.eds` duplicates.** A single `.eds` can hold up to
   **four 96-well plates
   as one 384-well run**, so one file may match several of the screen's barcodes. Narrow the
   `list_s3_objects` prefix (date / operator token) to stay under the 1000-object cap; if several match a
   barcode, take the latest timestamp (or confirm with the user).
2. **Download raw bytes — `.eds` is a binary ZIP container** (UTF-8 `read_s3_file` fails on it). Mode B:
   `download_s3_prefix` on the exact key. Mode A: `aws s3 cp` / `boto3` inside the kernel.
3. **Parse.** An `.eds` is a zip archive — unzip it and read the analysis payload from the SDS members
   (e.g. `apldbio/sds/analysis_result.txt` / `plate_setup.xml` / amplification data). Extract per well:
   well position, `Target` + `Reporter` (FAM = target, VIC = housekeeping), `Cq`/`Ct`, amp status. Then
   apply the **standard reduction pipeline**: 384→96 interleaved quadrant map + barcode assignment →
   pivot FAM vs VIC per well → `Cq_diff`/ΔCt → ΔΔCt vs the untreated-well control → `2^(−ΔΔCt)` →
   RNA-remaining % / knockdown %.
4. **Save** `qpcr_data.csv` (same schema as the index path) and **record the `.eds` filename + S3 key in
   Provenance** (this is the raw source of record).

*A QuantStudio **Result CSV** export is usually co-located in the same prefix (same basename +
`_Result_<YYYYMMDD_HHMMSS>.csv` — e.g.
`…_PE4002256_PE4002257_PE4002258_PE4002259_20260713_133638_Result_20260713_150430.csv`). You may parse
that instead — auto-detect the header row containing `Well Position`, split combined `Dyes` into
Reporter/Quencher, coerce `Cq` to numeric (drops `UNDETERMINED`), then the same 384→96 map. Either
works; the `.eds` is the source of record. (Ignore the `_Amplification Data_` / `_Multicomponent_` /
`_Raw Data_` / `_Melt Curve_` CSVs — the per-well Cq lives in the `_Result_`/`_Results_` CSV.)*

---

## STEP 5 -- QC analysis

**Confluence integrity check first.** Because the barcode is not in the confluence XML, assert each
plate has 96 wells, no duplicate labels, and **no two plates share an identical confluence vector**
(`np.allclose` pairwise) — a match means a file was mis-assigned; re-extract. (qPCR is exempt: its
barcode is carried in `source_plate_id`.)

**Confluence thresholds** (per plate × timepoint: mean confluence, %CV = std/mean×100 of sample wells):
| Metric | PASS | FLAG | FAIL |
|--------|------|------|------|
| Sample %CV | <20% | 20-25% | >25% |
| Mean confluence (sample wells) | >70% | 50-70% | <50% |

**qPCR QC** (per plate; sample wells only, exclude controls & `omit`):
| Metric | PASS | FLAG | FAIL |
|--------|------|------|------|
| Housekeeping Cq spread (sd of VIC Cq) | <0.5 | 0.5-1.0 | >1.0 |
| Housekeeping Cq level | <25 | 25-28 | >28 (low input) |
| Positive-control knockdown | >70% | 50-70% | <50% (assay not working) |
| Replicate %CV of 2^(-ddCt) at fixed dose | <25% | 25-40% | >40% |
Confirm any FAIL against the per-well `amp_status`/`cq_confidence` and the heatmap before finalizing.

Save `qc_summary.csv` to SAVE_DIR (one row per plate × readout).

### qPCR outlier removal (do BEFORE potency fitting) — produces the §6 before/after
Two exclusion rules, applied in order; keep a `before` (all wells) and `after` (cleaned) copy so the
report can show the delta:
1. **NO_AMP blanks** — drop wells with `amp_status != 'AMP'` (no amplification).
2. **Low-input wells** — flag any well whose **housekeeping (VIC) Cq > mean + 2·SD** of the plate's
   housekeeping Cq (≈ ≥8× less cDNA). At low input ΔCt is unstable and normalized mRNA-remaining
   inflates (a classic symptom: a single well reading hundreds of % mRNA remaining). Drop them.
Record: wells before/after, max mRNA-remaining before/after, benchmark 4-PL RMSE before/after,
benchmark KD50 before/after, and whether hit ranking / "beats benchmark" changed. **The cleanup should
tighten fits without reordering hits** — if the ranking moves, investigate before trusting it.
Save `qpcr_knockdown_clean.csv`.

### qPCR potency — 4-PL dose-response fit (KD50 / KD80 / max KD)
Per test siRNA and for the benchmark, fit a 4-parameter-logistic to mRNA-remaining vs dose with
**top fixed at 100%**; derive:
- **KD50 / KD80** = dose giving 50% / 80% knockdown (report "not reached" if the fit floor never
  crosses 80%);
- **Max KD** = 100 − fit floor (%);
- **Benchmark** = the positive control (e.g. SEMA3C SMARTpool) **pooled across all plates**;
- **Beats benchmark** = siRNA KD50 < benchmark KD50.
Save `qpcr_potency_clean.csv` and `qpcr_doseresponse_clean.csv`. Order the potency table by KD50
(most potent first). A genuine weak hit (low max KD that survives cleanup) is a real finding — flag it,
don't drop it.

### 3-pt screen "call" — strict triage cascade (drives the Q8 Triage table)
A 3-pt screen call is a **triage decision run as a strict cascade** — you only earn the right to ask the
next question if the current one passes. This is deliberately **coarser and inverted on potency** vs the
10-pt call: at 3-pt you bin into real-vs-noise and efficacious-vs-not, and you advance the molecules the
screen proved **potent but could not measure** (not the ones it already answered). Apply the gates in
order (this is exactly the logic in `assets/interactive_tables.html` `score3pt` / `#triage-3pt`):

0. **Plate validity (whole-plate gate, FIRST).** Confirm the plate is trustworthy before calling any
   siRNA: PPIB delivery control knocked down (transfection worked), FAM13A-pool positive control shows
   its expected deep KD (assay can see silencing), mock/non-targeting ~100% remaining (baseline valid),
   Z′ shows real pool-vs-mock separation, NTC/No-RT clean (no contamination/gDNA), GAPDH Cq stable across
   the plate (normalizer didn't drift). **Any fail → the whole plate is VOID → repeat**; do not call a
   single siRNA. Everything below assumes this passed.
1. **Data reduction per siRNA.** Collapse the 3 doses: ΔCq → ΔΔCq → %KD @20/2/0.2 nM, plus % of pool at
   the top dose. Average replicates here.
2. **Replicate precision — on the ΔCt scale.** Judge %CV on the **ΔCt (cycle) scale, NOT linear %** (the
   linear ratio inflates near deep knockdown, so a molecule can look noisy purely as a math artifact). If
   ΔCt precision is genuinely poor → **REPEAT (too noisy)**, don't call.
3. **Reality check — monotonic?** True dose response has %KD rising or flat with dose. Rebound at the top
   dose or zig-zag is a **confound** (usually high-dose lipid/siRNA toxicity distorting the normalizer) →
   **FAIL — confound**; investigate, do not fit/bin potency.
4. **Efficacy gate — the primary flip.** Compare % of pool @top to the bar (e.g. ≥80%). Below the bar →
   **FAIL — inactive/weak**. This comes **before** potency: if it can't silence deeply even at 20 nM, a
   precise KD50 tells you nothing actionable.
5. **Potency read + resolution status — the advancement branch.** Read potency coarsely from %KD @0.2 nM.
   Then classify KD50:
   - **Bracketed** (transition sits inside 0.2–20 nM; typical of a weaker molecule) → you already have a
     usable coarse KD50 → **HOLD / DROP** (a 10-pt run would just re-measure a number you have), unless
     efficacy is high enough to warrant a precise value.
   - **Extrapolated** (deep %KD even @0.2 nM → true KD50 below the lowest dose) → potency is real but
     **unresolved** — the case the 3-pt grid can't pin → **ADVANCE to 10-pt**.
6. **Redesign the follow-up for advancers.** Shift the 10-pt range **downward** (top ~2 nM stepping into
   low pM) so the sub-0.2 nM KD50 lands inside the sampled range and is **interpolated**, not
   extrapolated again.

### 10-pt confirmation "call" — terminal cascade (drives the Q8 Levers table)
The 10-pt call is the **terminal grade** (Advance / Hold / Fail + a priority), not a hand-forward. It has
the **same backbone** as the 3-pt cascade (plate gates → per-siRNA reduction → reality/quality → efficacy
→ potency) but a **richer front end** — because a full 4-PL fit lets you fully characterize each molecule,
three things change (this is exactly `assets/interactive_tables.html` `score10pt` / `#levers-10pt`):

0. **Plate validity (whole-plate gate, FIRST)** — same as 3-pt (PPIB delivery, FAM13A-pool positive,
   mock ~100%, Z′, NTC/No-RT, GAPDH Cq stable). Any fail → **VOID → repeat plate**.
1. **Per-siRNA reduction + 4-PL fit** → KD50 (±CI), KD80, KD max, Hill, % pool, R².
2. **Hard quality gate (fit quality).** R² ≥ 0.98, ≥ 8/10 usable points, converged fit. Fail → **FAIL /
   repeat** (bad data / non-converged). **Monotonicity folds in here** — a good 4-PL fit with acceptable
   R² is implicitly monotonic and well-shaped, so it is no longer a separate node as in the 3-pt tree.
3. **Fit-trustworthy guardrail (soft).** Hill slope 0.7–1.5 and a tight KD50 CI (≤ ~5× fold). If off →
   **HOLD / repeat** (imprecise / odd curve shape) — *not* a hard fail; the molecule may be fine but the
   curve needs a rerun.
4. **Efficacy gate — the primary flip.** % of pool @top: **< 60 → FAIL (inactive/weak)**; **60–80 → HOLD
   (capped efficacy)**; **≥ 80 → continue** to potency.
5. **Potency TIER (graded, not resolve/advance).** The 10-pt curve already brackets KD50, so nothing is
   left to resolve — potency sets the **final priority**: **KD50 ≤ 0.5 nM → ADVANCE (top priority)**;
   **≤ 5 nM → ADVANCE**; **> 5 nM → HOLD (efficacious but too weak / needs high dose)**.

Contrast with 3-pt: the 3-pt tree is a **triage** that sorts real-vs-noise and hands winners to a further
(10-pt) screen; the 10-pt tree is the **terminal call** that grades survivors into Advance/Hold/Fail with
a priority. Both share gates 0–1 and the efficacy flip.

### Replicate %CV — report on TWO metrics side by side
%CV on the **linear mRNA-remaining** ratio is inflated at the extremes (deep knockdown at top dose,
noisy sub-nM baseline), so a high linear %CV does NOT by itself mean the assay is imprecise. Compute
%CV per (siRNA/control × dose) on **both** the linear mRNA-remaining and the **ΔCt (log domain)**;
report each median. ΔCt %CV near ~5% with a high linear %CV = ratio-metric inflation, not noise.
Flag cells >25% in the tables (§6).

### Confluence outlier root-cause (per FAIL/FLAG plate)
For each flagged plate, decide **mechanical vs biological**:
- Plot confluence **vs dose** across the plate. A **U-shape** (high at both dose extremes, trough in
  the middle columns) that **also hits the control rows** is dose-independent → a spatial / seeding /
  dispense / evaporation artifact, NOT an siRNA effect.
- A monotonic dose-dependent drop that spares controls could be biology (or acute transfection
  cytotoxicity if it appears at T1 — too early for knockdown).
State what, where, how-determined (which threshold breached), and why (mechanical vs biology). If the
plate is outside the qPCR subset, note there is no knockdown readout to salvage — it is flagged /
re-plated, not "removed".

### Repeat decision (batch go/no-go — §8)
Assemble an explicit verdict from: (a) **assay validity** (housekeeping uniform, wide dynamic range,
well-behaved positive control vs standard acceptance criteria); (b) **robustness to QC** (did removing
flagged wells move KD50 / hit order?); (c) **precision- vs validity-limiting** defects (where the noise
sits on the curve); (d) **per-plate** cleanliness; (e) **upstream confluence** clean for the qPCR
plates. Then state **when a repeat WOULD be justified** (decision-grade absolute potency → narrow
low-dose titration; single worst-input plate re-run; confirm a weak hit; re-plate any confluence-FAIL
plate that sits outside the qPCR set). Prefer targeted follow-ups over full-batch repeats.

### Confluence T1-only (Day0) interim mode
When only Day0 (T1) exists: Day0 confluence is a **seeding-density** metric, near saturation on a
dense seed — **do not gate on the mean-confluence thresholds at T1**; score on spatial uniformity
(sample %CV). The mean-confluence and dose-response viability call belong to T2. A dose-dependent
confluence drop at T1 is likely acute cytotoxicity/dispense fault, not knockdown — route to Fig 10.

---

## STEP 6 -- Generate figures

Always use absolute SAVE_DIR paths for `plt.savefig()`. Inspect dtypes before writing figure code.
Plate ordering: biological timestamps (seeding or T1 imaging / qPCR run time), not plate ID numbers.
Mode A: one figure per notebook cell. **Mode B:** one `matplotlib` script via the sandbox shell
(`pip install --break-system-packages matplotlib numpy pandas`), saving PNGs; **view at least one PNG
to verify no overlapping/truncated text or clipped legends** before assembling the HTML (STEP 7).

**Interpretation note on every plot (required).** Each figure must be accompanied by a brief note on
how to read/interpret it — one or two sentences stating what the reader should conclude (e.g. what a
"good" plate looks like, which direction means more potent, what a breach of a threshold means). In the
HTML this is the figure's `.guide` "How to read" box (STEP 7); no plot ships without one.

**Reference examples (canonical target style).** Figures marked *(mimic …)* below have a reference PNG
in `assets/examples/` (see its `README.md` for the map). **Open the reference before coding that figure
and match its layout, colors, ordering, annotations, and reference lines** — rendered on the report's
dark theme. These are the house style; do not diverge from them.

**Regenerate after outlier removal.** After STEP 5 qPCR outlier removal, **regenerate every plot whose
values change once the flagged wells are dropped** (dose-response, knockdown bars/lines, ranked
RNA-remaining, potency, %CV) **and the Q8 decision table** — i.e. a **new 10-pt Per-siRNA Summary +
Levers table, or a new 3-pt Triage table**, computed on the cleaned data. Present the cleaned versions
in a **dedicated "Regenerated after QC cleanup" section** (§6.1) so pre- and post-cleanup views sit side
by side. **Do NOT overwrite the original tables/plots** — keep both the original and the regenerated
respective table so the effect of the cleanup is auditable.

**Confluence figure set (Figs 1-10):**
- **Fig 1** Representative plate map — read `*platemap.png` if present, else derive from the plate-map
  DB (STEP 2). Use `scripts/plate_colors.py` for all color/dose-tier/well-position logic (encodes the
  well_row int-1-8 and well_column int64 gotchas). Single-dose = light bg/rectangles/`SINGLE_DOSE_COLORS`;
  3-pt DRC = dark bg/circles/`get_compound_color_3pt`; 10-pt DRC = dark bg/circles/`get_10pt_shade`.
- **Fig 2** Assay parameters card — two columns; show **Project ID** and **Campaign ID** as separate
  labeled fields with ` - ` separators, never merged.
- **Fig 3 — Workflow summary figure** *(mimic — `assets/examples/fig3_workflow_summary.png`; use **pastel
  colors**)* Vertical flowchart of the screen's work orders in execution order, one **full-width rounded
  box per work order** connected by down-arrows. Each box shows: the **Order ID** (italic, top-left, e.g.
  "Order 3021"), the **step title** (bold, centered — Onboard plates · OptiMEM addition · Incubation ·
  RNAiMAX addition · RNAiMAX+siRNA dispense · Cell seeding · T1 SparkCyto scan (~4 h post-seed) · T2
  SparkCyto scan (~18 h post-seed)), and a centered detail line **`<instrument>  |  <start> → <end>`**
  (e.g. "Bamboo / Hamilton  |  2026-06-24 20:04 → 20:26"; instruments: Bamboo/Hamilton, Multidrop,
  Incubator, BioTek MFX, TE-SPARKCYTO-04). One **soft pastel** fill per step (distinct hue per box);
  white bold titles, muted detail text. Note partial-plate steps in the box (e.g. T2 "Order 3033
  (6/12 plates)"). Pull Order IDs / instruments / start→end from the Cellario/Groot work-order logs
  (STEP 3). Replaces the old plain workflow diagram.
- **Fig 4 — Workorder Gantt: liquid handling** *(mimic — `assets/examples/fig4_workorder_gantt.png`)* One
  figure, **one stacked panel per work order** for the four liquid-handling WOs — **OptiMEM addition ·
  RNAiMAX addition · RNAiMAX+siRNA dispense · Cell seeding**. Each panel is a **per-plate processing
  timeline** on a time (HH:MM) x-axis: one colored dot per plate at its start time, staggered in
  processing order, labeled `N. <plate short id>`; panel title = the WO name (accent color) with a grey
  subtitle **`Order <id> · plate start times · span <N> min · cadence ~<x> min/plate`**. Dark bg; one
  stable color per plate across panels; labels outside dots (no overlap). Use the per-WO per-plate start
  times from the work-order logs (STEP 3, `run_log_events.csv`). Where start→end durations are available,
  a start→end bar per plate is an acceptable alternative to the dot.
- **Fig 4b — Workorder Gantt: imaging** *(mimic — `assets/examples/fig4_workorder_gantt.png`)* Same
  figure-2 style, one figure with **one panel per imaging WO — T1 SparkCyto scan and T2 SparkCyto scan** —
  each a per-plate scan-start timeline (dot + `N. <plate>`, span + cadence subtitle). Note plates missing a
  T2 scan (e.g. "6/12 plates"). Keep plate colors consistent with Fig 4.
- **Fig 5** *(mimic — `assets/examples/fig5_t1_confluence_heatmaps.png`)* T1 confluence heatmaps, **one per
  plate in seeding/read order** (8×12, YlOrRd, vmin=0 vmax=100; spine colored by QC status; per-plate title
  "PExxxx (STATUS, %CV=…)"; shared "Confluence %" colorbar).
- **Fig 6** T2 confluence heatmaps — same style and **seeding order** as Fig 5 (note plates without a T2 read).
- **Fig 7** *(mimic — `assets/examples/fig7_t1_vs_t2_mean_confluence.png`)* Mean confluence per plate,
  **T1 vs T2 grouped bars with ± SD whiskers** and **individual sample-well dots** jittered over each bar;
  value labels "mean ±SD"; ref lines 70% / 50%; order by seeding. (The example shows the T1 panel; produce
  the grouped T1-vs-T2 version.)
- **Fig 8** *(mimic — `assets/examples/fig8_cv_by_plate.png`)* Sample-well %CV per plate — bars + value
  labels; **orange FLAG > 20%** and **red FAIL > 25%** dashed lines; y→~30; with a **status table beneath**
  (plate / read time / mean sample % / %CV / PASS-FLAG-FAIL). T2 when available, else T1.
- **Fig 9** QC status cards, **one per plate, ordered by seeding** (PASS/FLAG/FAIL colored).
- **Fig 10** Root-cause analysis (per flagged plate: heatmap + histogram).

**qPCR figure set (Figs Q1-Q11)** — generate when the qPCR readout is present. Figures marked
*(mimic)* have a reference PNG in `assets/examples/` — **open it before coding and match its layout,
colors, ordering, annotations and reference lines** on the report's dark theme.
- **Fig Q1** qPCR plate map (reuse Fig 1 logic; color by compound/dose).
- **Fig Q2** Assay parameters card — add target gene(s), housekeeping gene, qPCR instrument, run datetime.
- **Fig Q3** *(mimic — `figQ3_housekeeping_cq.png`)* Housekeeping Cq **per compound, per well, per plate** —
  strip/scatter; x = compound ordered by PE plate with **dashed plate separators + plate-label boxes**;
  **include each plate's controls** — the untreated/mock (`ctrl`) column first, plus the **siPPIB assay
  control** and the **positive/SMARTpool benchmark** — as their own x entries on every plate alongside the
  test compounds; color by concentration (untreated = grey, 0.2 nM = red, 2 nM = blue, 20 nM = green);
  bright dots, enlarged x-font; dashed Cq threshold line (e.g. Cq = 25); legend. Confirms uniform
  housekeeping input across samples AND controls with no dose/plate drift. *(In Q3 the siPPIB well shows
  only **housekeeping input** (GAPDH Cq) — it is NOT the delivery proof; PPIB knockdown is Fig Q3b / Q4.)*
- **Fig Q3b — Delivery control (PPIB knockdown per plate).** A dedicated panel proving **siRNA got into
  the cells**: one **PPIB knockdown %** bar per plate for the siPPIB delivery control (mean ± SEM across
  its replicate wells), with a **pass line (e.g. ≥ 70% KD)** and PASS/FAIL coloring per plate. PPIB is the
  *delivery/transfection* control (siPPIB targets PPIB); high PPIB KD on a plate = delivery worked there.
  This is the graphical companion to the Q8 plate-level "PPIB siRNA (delivery)" validity gate. Compute
  from the PPIB (FAM) vs housekeeping (VIC) Cq in the siPPIB wells — not from the target-gene probe.
- **Fig Q4a — GOI % knockdown by tested siRNA (mirror of Q5, knockdown view)** *(match Q5's layout —
  `figQ5_ranked_rna_remaining.png`)* Cross-siRNA grouped bars of **target-gene (GOI) % knockdown** at the
  three doses — **0.2 nM teal `#5eead4` · 2 nM blue `#5dade2` · 20 nM amber `#f5b041`** — with **±SEM
  whiskers on EVERY bar**, **ranked by the 20 nM dose (most knockdown left)**. Then a **pooled controls
  block** at the right (dashed divider, *"pooled controls (all plates)"*): SEMA3C SMARTpool (+) green-edged
  and mock (−) grey (~0% KD), each **mean ± SEM pooled across all replicates and all plates** (state n).
  This is the **knockdown-axis mirror of Q5** (Q5 = mRNA-remaining ranked on 0.2 nM; Q4a = %KD ranked on
  20 nM), so the **20 nM-toxicity signature shows as the amber (20 nM) bar DIPPING BELOW the blue (2 nM)
  bar** for affected siRNAs — keep it visible. Generated for BOTH designs (for 10-pt, the three canonical
  doses sampled from the curve). x = full registry IDs. `knockdown % = (1 − 2^(−ΔΔCt)) × 100`.
- **Fig Q4b (3-pt DRC)** *(mimic — `figQ4_3pt_knockdown_bars.png` for layout; but use the **harmonized Q5
  dose palette** below, not the reference's older amber/purple/blue)* Per-plate knockdown — one subplot
  per plate; dose-grouped bars per siRNA in the **Q5-harmonized dose colors: 0.2 nM teal `#5eead4` · 2 nM
  blue `#5dade2` · 20 nM amber `#f5b041`** with **white individual-replicate dots**; **each plate also
  shows its controls as their own bar groups — the siPPIB delivery control (proves delivery on that plate)
  and the SMARTpool/positive benchmark**; status-colored subplot titles; single figure-level legend
  outside the panels; **within each plate, order the siRNAs by 0.2 nM efficacy (most potent left),
  mirroring Q5**; x = full registry ID. **Error bars (mean ± SEM of the replicate wells) on EVERY bar —
  samples and controls.** **Preserve the 20 nM-toxicity signature — do NOT smooth or reorder it away: for
  toxicity-affected siRNAs the amber (20 nM) knockdown bar visibly DIPS BELOW the blue (2 nM) bar** (the
  knockdown-axis mirror of Q5, where 20 nM mRNA-remaining sits *above* 2 nM); plot the real values and
  call it out. Keep the green dashed benchmark-20 nM reference line. Restate
  `knockdown % = (1 − 2^(−ΔΔCt)) × 100` in the caption.
- **Fig Q4b (10-pt DRC)** *(mimic — `figQ4_10pt_doseresponse_lines.png`)* Per-plate dose-response — one
  subplot per plate; **one line per siRNA and per control** on the plate (the **siPPIB delivery control**
  + SMARTpool benchmark drawn grey dashed) of mRNA-remaining % vs dose (nM, log, 20 → 0); 50% orange
  dashed + 100% dotted refs; figure-level legend; x = full registry ID. **SEM error bars on EVERY point —
  samples and controls.** Where the top (20 nM) point rises above 2 nM, that is the same 20 nM-toxicity
  signature — keep it visible. (Grouped bars are acceptable for few doses, but the line form is preferred
  for a full 10-pt series.)
- **Fig Q5** *(mimic — `figQ5_ranked_rna_remaining.png`)* Target mRNA-remaining % across ALL test siRNAs,
  **grouped bars showing ALL THREE doses per siRNA** — 0.2 nM teal `#5eead4`, 2 nM blue `#5dade2`,
  20 nM amber `#f5b041` **(labeled "tox")** — with **±SEM whiskers on EVERY bar**. **Rank the siRNAs by
  the non-toxic 0.2 nM dose (most potent left → highest 0.2 nM remaining right)** — NOT by 20 nM (the
  20 nM/amber bar often sits *above* the 2 nM bar because of 20 nM toxicity; call this out in the title
  and cross-ref Fig Q4a). x = full registry IDs.
  - **Pooled controls block at the right**, separated by a dashed vertical divider and a *"pooled
    controls (all plates)"* label: the **SEMA3C SMARTpool (+) positive control** (green-edged bars) and
    the **mock (−) negative control** (grey, ≈100%), each **mean ± SEM pooled across all replicates and
    all plates** (state n). *(Do NOT put the siPPIB delivery control here — it targets PPIB, a different
    gene than this target axis; delivery lives in Fig Q3b / Q4 / the Q8 gate.)*
  - **Reference lines:** a **dotted line = pooled benchmark at 0.2 nM** (state its value, e.g. 23%) and a
    **solid line = 50% remaining**. **Do NOT hard-cap y at 100%** — some bars/controls exceed 100 (mock
    ≈100, weak siRNAs higher); give headroom (~110–120). `mRNA remaining % = 2^(−ΔΔCt) × 100`.
- **Fig Q6** *(mimic — `figQ6_potency_dotplot.png`)* Potency dot plot — one row per siRNA (label + plate);
  ● KD50 joined to ◆ KD80 on a **log dose axis**; max-KD % printed at far left; "KD80 not reached" marks a
  ceiling < 80%; the pooled benchmark (SMARTpool) as its own row; legend; **indicate the direction of
  potency (annotate "← more potent")**. Built from `qpcr_potency_clean.csv`.
- **Fig Q7** Replicate %CV, **two panels side by side** — A: linear mRNA-remaining, B: ΔCt (log). Same
  wells, color capped at 50%. Pair with the two %CV tables (cells > 25% red) in the body.
- **Fig Q8 — design-specific decision table(s)** (HTML, not a PNG). Build from
  `assets/interactive_tables.html` and emit **two tables for the matching design**: a **simplified static
  summary** first, then the **full interactive** table.
  - **Simplified summary** (`#simple-10pt` / `#simple-3pt`) — a clean, standard-threshold at-a-glance
    readout. 10-pt: siRNA / Role / KD50 / KD80 / KD max / % pool / R² / **Call** (colored). 3-pt: siRNA /
    Role / %KD @20 / @2 / @0.2 / % pool @top / Cq SD (no Call column). Highlight the benchmark row
    (`.benchrow`). Fill the 10-pt Call with the standard-threshold result so it agrees with the
    interactive table's default.
  - **Full interactive** (`#levers-10pt` / `#triage-3pt`) — fill one row per siRNA (`data-*` attributes
    drive the scoring); the user can **edit the thresholds in the browser** and the cell colors +
    Call/Advance column recompute live.
  - **10-pt DRC → "Per-siRNA Summary + Levers"** (`#levers-10pt`): a plate-level validity gate strip
    FIRST (PPIB delivery, mock baseline, Z'-factor, NTC/No-RT, GAPDH Cq SD — any fail voids the plate),
    then per-siRNA POTENCY (KD50/95%CI/KD80) · EFFICACY (KDmax, % pool — primary dial) · GUARD (Hill) ·
    QUALITY GATES (R² / pts / CqSD) · OUTCOME. The Call is the STEP 5 **terminal cascade**: VOID (plate
    gate fail) → FAIL/repeat (quality gate: bad/non-converged fit) → HOLD·repeat (fit-trust: Hill or CI
    off) → FAIL·inactive/weak (< 60% pool) / HOLD·capped (60–80%) → potency tier ADVANCE·top (KD50 ≤ 0.5
    nM) / ADVANCE (≤ 5 nM) / HOLD·weak-potency (> 5 nM). Graded terminal grades, not a hand-forward.
  - **3-pt DRC → "3-Point Triage"** (`#triage-3pt`): measured %KD @20/2/0.2 nM · decision inputs
    (% pool @top, monotonic?, KD50 status) · Trust (ΔCt CqSD) · **Call** from the STEP 5 **strict
    cascade** — VOID (plate gate fail) → REPEAT (poor ΔCt precision) → FAIL·confound (non-monotonic) →
    FAIL·inactive/weak (below efficacy bar) → HOLD/DROP (KD50 bracketed) → ADVANCE to 10-pt (KD50
    extrapolated / unresolved). Footnotes carry the full cascade + the advancer dose-redesign note.
  *(This replaces the old static ranked table — Fig8 per the instructions.)*
- **Fig Q10** Outlier identification — A: housekeeping Cq per well with the **mean+2SD** threshold
  (red = excluded low-input); B: inflated mRNA-remaining vs housekeeping Cq (the gross-artifact well sits
  in the excluded group).
- **Fig Q11** Dose-response **before vs after** cleanup — same axes; the pre-cleanup artifact spike is
  visible, the cleaned curves tighten at low dose while ranking/curve shape are preserved.

> **Removed:** the old **Fig Q9** (per-plate findings & score card) is no longer generated — drop it and
> its report §7.

**Assay-design gating (which qPCR figures to generate):**
- **10-pt DRC:** generate all qPCR figures **except the old Q8 ranked table** — Q8 is now the interactive
  *Per-siRNA Summary + Levers* table.
- **3-pt DRC:** generate all qPCR figures **except Q4b (per-plate dose-response) and Q6 (potency dot
  plot)** — 3 doses don't support a reliable 4-PL potency call; the *3-Point Triage* table (Q8) carries the
  per-dose %KD and the advance decision instead. **Q4a (cross-siRNA %KD, 3 doses ranked on 20 nM) IS
  generated** — it is the 3-dose knockdown summary and is especially apt for a 3-pt screen.
- **Q4a** is generated for both designs (for 10-pt it uses the three canonical doses 0.2/2/20 nM).
- Always emit only the readouts/figures the data supports; note any skipped figure and why.

**Figure → template-slot map** (STEP 7 `assets/report_template.html`): plate map→`FIG_PLATEMAP`,
Fig3 workflow-summary→`FIG_TIMELINE`, Fig4 workorder-gantt-liquid→`FIG_WORKFLOW_ORDER`, Fig4b workorder-gantt-imaging→`FIG_WORKORDER_GANTT_IMG`, Fig5→`FIG_T1_HEATMAPS`, Fig6→`FIG_T2_HEATMAPS`,
Fig7/8→`FIG_MEAN_CV`, Fig9→`FIG_STATUS_CARDS`, Fig10→`FIG_ROOTCAUSE`; Q1→`FIG_Q1`, Q2→`FIG_Q2`,
Q3→`FIG_Q3`, Q3b→`FIG_DELIVERY`, Q4a→`FIG_Q4A_GOI`, Q4b-3pt→`FIG_Q4`, Q4b-10pt→`FIG_Q4_10PT`, Q5→`FIG_Q5`, Q6→`FIG_Q6`, Q7→`FIG_CV`,
Q10→`FIG_OUTLIER_ID`, Q11→`FIG_BEFORE_AFTER`. **Q8** is the interactive decision table from
`assets/interactive_tables.html` — HTML+JS built directly into §5, **no image slot**. (Q9 removed.)

**Run-log view (Figs R1-R2)** — generate for DATA_OP options 1 & 2 (WF run logs by plate):
- **Fig R1** Per-plate WF Gantt — one horizontal bar per plate × WF (WF1/WF2[/WF3]) spanning
  start→end from `run_log_events.csv`; plates on the y-axis ordered by first WF1 timestamp; color by
  WF. Mark error/warning events. WF labels on y-axis ticks, not inside bars (Gantt gotcha).
- **Fig R2** Duration + error summary — grouped bars of per-WF duration by plate, with an error-count
  annotation; flag plates whose duration or error count is an outlier vs the plate set.
Also emit the plate × WF summary table (start, end, duration, error count) into the report body.

**Summary (§1 content):** KPI cards + key findings + QC summary table, **covering every readout that
ran** — not confluence only. Whenever qPCR ran, the summary must state the knockdown headline (how many
siRNAs beat the benchmark, best KD50 + max KD, any weak hit), the housekeeping-QC result, and the
outlier-cleanup outcome (wells excluded + that hit ranking held), and add qPCR KPI cards (qPCR plates,
beat-benchmark, best KD50, best max KD). See STEP 7 §1 for the exact readout-complete rule.

---

## STEP 6.5 -- QC verification agent (calculations & quantitative results) — GATE before STEP 7

**Run an independent QC pass over every number before the report is approved.** Its sole job is to
verify all calculations and quantitative results to **100% precision** — it must **PASS** before STEP 7
ships. **Spawn it as a separate subagent** (Task tool) so it re-derives values from the source data
rather than trusting the numbers STEP 4Q/5/6 already produced (an independent recompute, not a re-read).

1. **Input validation — audit every numerical input, constant, and formula variable.** Confirm each is
   correct, has the right **units**, and is not missing or mis-set: confluence well-area denominator
   (state `3.217e7 µm²`), Cq threshold, low-input threshold (the actual `mean+2SD` value), the
   untreated/control column, the dose values (nM) and that concentrations/Cq were coerced to numeric,
   the benchmark identity, the gate thresholds (R² ≥ 0.98 · pts ≥ 8/10 · CqSD ≤ 0.3 · % pool 60/80 ·
   Hill 0.7–1.5 · KD50 tiers 0.5/5 nM), replicate **n**, and the 384→96 quadrant→barcode map. Cross-check
   these against §9 Calculations & formulas — every constant used must appear there.
2. **Execution verification — recompute and match within tolerance.** From the raw/source CSVs
   (`confluence_data.csv`, `qpcr_data.csv`, the raw `.eds`/Result CSV) independently recompute and confirm
   they equal the reported/index values: confluence % (`TotalAreaInUm2 / well_area × 100`) and %CV;
   `ΔCt = Cq(target) − Cq(hk)`; `ΔΔCt` vs the per-plate untreated mean; fold change `2^(−ΔΔCt)`;
   mRNA-remaining % and knockdown %; 4-PL KD50/KD80/max KD + fit RMSE; beats-benchmark; PPIB delivery KD;
   Z′; pooled-control mean ± SEM; and the outlier flags (NO_AMP, housekeeping Cq > mean+2SD). **Cross-check
   the index `knockdown_pct`/`mrna_remaining` against the recompute**, verify the interleave/barcode
   assignment, and confirm each **figure/table value matches its CSV** (Q8 cells, Q5/Q4a bars, KPI cards,
   §9 rows). Tolerance: exact for integer counts; ≤ ~0.5 % relative for derived floats (rounding-display
   diffs are OK; logic/param mismatches are not).
3. **Discrepancy flagging — before final output approval.** Write `qc_verification.csv`
   (`quantity, reported, recomputed, delta, status`) + a short log. **Any mismatch, miscalculation, or
   missing parameter is FLAGGED** and the agent returns a verdict: **PASS** (all quantities verified) or
   **FAIL** (itemized discrepancies).

**Gate:** STEP 7 ships **only after QC PASS**. On FAIL, fix the computation (or the input) and re-run
STEP 6.5; do not present unverified numbers as final — if a value can't be verified, mark it explicitly
as unverified in the report rather than approving it. Save `qc_verification.csv` to SAVE_DIR; surface the
verdict as a **§1 QC badge**, and **list every FAIL finding in the report's §9 "QC verification"
section** (quantity · where · reported · recomputed · Δ · status, from `qc_verification.csv`).

---

## STEP 7 -- HTML report (build from the master template)

**Build from `assets/report_template.html`** — it is the canonical design system and layout; do not
hand-roll a new stylesheet. Copy it, fill the `{{TOKENS}}`, base64-embed each STEP 6 PNG into its
`FIG_*` slot (per the figure→slot map in STEP 6), and **delete any section that does not apply** to the
chosen DATA_OP / findings. Mode A may still nbconvert a notebook, but the deliverable must match this
template's structure and CSS.

**Master report = one document combining every readout that was run** (confluence + qPCR + run logs as
applicable). When it supersedes earlier standalone reports, say so in the header sub-line and keep the
old files for reference (list them in Provenance).

**Report file name (required convention):** `<screen>_<celltype>_<DRC>_<N>plates_<seeddate>.html`, e.g.
`MASH3_3T3_3pt_6plates_2026Jul8.html`. Build the tokens as:
- `<screen>` — short screen/project name, no spaces (e.g. `MASH3`).
- `<celltype>` — cell line short name (e.g. `3T3`, `A549`), not the Cins ID.
- `<DRC>` — the assay design token: `3pt`, `10pt`, or `arrayed` (single-dose). Use the **actual** dose
  scheme resolved from the plate map, not the collection name.
- `<N>plates` — total plate count in the screen (e.g. `6plates`).
- `<seeddate>` — the seed/transfect (screen start) date as `YYYYMonD` — 4-digit year, 3-letter month,
  day with **no leading zero** (2026-07-08 → `2026Jul8`).
Join with single underscores; the `.csv` data files may reuse the same stem.

**Section layout (renumber the TOC to match what you emit):**
1. **Executive summary** — a `.summary` block that is **readout-complete: it must summarize every
   section emitted below.** Include a bolded line for each of:
   - **Confluence verdict** (if §3 present) — X/Y PASS + one-line pattern.
   - **qPCR knockdown verdict** (if §5 present) — how many siRNAs beat the benchmark, best KD50 + max
     KD, any weak hit, and that housekeeping was uniform (knockdown is genuine).
   - **qPCR QC-cleanup note** (if §6 present) — wells excluded (NO_AMP + low-input) and that the hit
     ranking / KD50 held after cleanup.
   - **Repeat verdict** (§7) — one-line go/no-go.
   - **QC-verification verdict** (STEP 6.5) — a badge: **`.ok` "QC verified — all N calculations
     independently recomputed and matched"** on PASS, or a **`.note` listing the flagged discrepancies**
     on FAIL. The report is only approved on PASS; never present a FAIL report as final.
   Then a `.kpis` strip whose cards match the emitted readouts: confluence → plate count + PASS count;
   qPCR → qPCR plates, beat-benchmark, best KD50, best max KD. **Never ship a summary or KPI strip that
   omits a qPCR section that appears in the body** (see the readout-complete gotcha).
2. **Screen design & timeline** — plate map, timeline, and the WF processing-order figure, each in a
   `.fig` with a `.cap`; add a `.guide` "How to read" box where a reader could misread it.
3. **Confluence QC (T1/T2)** — heatmaps, mean/%CV, status cards.
4. **Confluence outlier** — one section per FAIL/FLAG plate: a `.note` (what/where/how-determined/why
   mechanical vs biology) + the root-cause figure + a representative **well-image grid** (STEP 8).
5. **qPCR knockdown** — a `.note` methods block (ΔCt/ΔΔCt/mRNA-remaining, KD50/KD80 from 4-PL,
   quadrant→plate mapping); the qPCR figures **Q3 housekeeping Cq, Q4 (10-pt lines / 3-pt bars — 3-pt
   screens SKIP Q4), Q5 ranked RNA-remaining, Q6 potency dot plot (3-pt screens SKIP Q6)**; the **Q8
   interactive decision table** (10-pt *Per-siRNA Summary + Levers* or 3-pt *Triage*, from
   `assets/interactive_tables.html`, editable thresholds); and §5.1 **Q7 replicate %CV** (two panels +
   the two %CV tables, cells >25% red). Q1/Q2 (qPCR plate map / params) are optional if §2 already
   covers them.
   **§5 must state clearly (a) what analysis was done** — the ΔΔCt knockdown pipeline, per-plate
   normalization, 4-PL potency, housekeeping/%CV QC, and the outlier check performed (NO_AMP +
   housekeeping Cq > mean+2SD) — **and (b) end with an explicit outlier conclusion** answering *"Were any
   outliers detected?"*: if **yes**, state how many wells/which and point to §6 for the removal &
   before/after; if **no**, say so plainly (e.g. "No outliers detected — no wells excluded; §6 omitted").
   Put this as a short `.note`/`.ok` conclusion box at the end of §5.
6. **qPCR outlier removal — before/after** — `.note` (rule: NO_AMP + housekeeping Cq>mean+2SD), **Fig
   Q10** (outlier ID) + **Fig Q11** (before/after), the **what-changed table** (wells, max mRNA-remaining,
   RMSE, KD50 stability, ranking), and **§6.1 "Regenerated after QC cleanup"** re-emitting every plot
   whose values changed (Q4/Q5/Q6/Q7) **plus a new regenerated Q8 decision table** — QC-cleaned, with the
   originals kept above (not overwritten).
7. **Repeat evaluation** — a `.decision` box (Yes/No + rationale) followed by the (a)-(e) criteria and
   a "when a repeat WOULD be justified" paragraph (from STEP 5 repeat-decision).
8. **Calculations & formulas** — a table listing **every computed quantity with its exact formula**
   (confluence % and %CV; ΔCt, ΔΔCt, fold change, mRNA-remaining %, knockdown %; KD50/KD80 4-PL, max
   KD, beats-benchmark, fit RMSE; low-input threshold = housekeeping Cq > mean+2SD; ΔCt %CV; WF
   duration). Fill in the actual values used (well-area denominator, control column, Cq threshold).
   **Every number shown anywhere in the report must trace to a row here — add a row for anything you
   compute that isn't listed.**
9. **QC verification** (from STEP 6.5) — the QC verdict + a **FAIL-findings table listing every flagged
   discrepancy** (quantity · where fig/table · reported · recomputed · Δ · status), sourced from
   `qc_verification.csv`. On PASS: an `.ok` badge and an empty findings table. On FAIL (soft gate): a
   `.note` verdict **and one row per discrepancy** here. **Highlight the failed items for visibility**:
   give each discrepancy row `class="failrow"` (red-tinted row + red left accent), and in the body wrap
   each affected value in `<span class="unverified">…</span>` (red-highlighted) so a flagged number
   stands out wherever it appears (KPI card, figure caption, table cell). This section is always present
   when any quantitative readout ran.
10. **Provenance** — a `.foot` with S3 paths, exclusion rules, the data-file list, author initials, and
   report datetime.

> **Note:** there is **no per-plate findings / score-card section** (former §7) — it was removed.

**House rules (enforced by the template; keep them):** the `<h1>` title follows the **exact format**
`{{SCREEN_NAME}} — {{CELL_LINE}} — {{DRC}} DRC — QC & Knockdown Report — {{SEED_DATE}}` (DRC = `3pt` /
`10pt`, or `arrayed` for single-dose; SEED_DATE = seed/transfect date `YYYY-MM-DD` at the end), e.g.
"MASH3 — 3T3 — 3pt DRC — QC & Knockdown Report — 2026-07-08"; dark theme + the `:root` palette; every figure
has a `.cap` **and a brief `.guide` "How to read" interpretation note (required on every figure)**;
header `.meta` carries Project (EINS-PRJ), Campaign
(CACT-PRJ), cell line (+Cins), target, **confluence instrument + reader**, **qPCR instrument
(`QPCR_INSTRUMENT` = QuantStudio model + serial + block, from `qpcr_run`)**, seed/transfect date,
**author initials**, report datetime; a 2-column `.toc`; status colors PASS #4CAF50 / FLAG #FF9800 /
FAIL #F44336; no overlapping/truncated text. **Show every formula:** restate each figure's/metric's
formula in its caption AND collect them all in §9 Calculations & formulas — do not present a computed
number without its formula somewhere in the report.

---

## STEP 8 -- SparkCyto well images (representative grid)   [confluence readout]

Used for §4 root-cause. **Binary JP/TIFF cannot be base64-inlined** (`read_s3_file` is UTF-8 only and
they are large), so render them as a **`.grid` of download cards**, not inline images: pick ~10 wells
spanning the deficit (plus a within-plate healthy reference), and for each emit an `<a>` card showing
the well ID + confluence %, with the border-top and percent **colored by status** (PASS #4CAF50 /
FLAG #FF9800 / FAIL #F44336) and linking to the hosted download.
- Locate each plate's folder from STEP 3 `imaging_timestamps.csv`; image types `N_Bf_Processed`,
  `AC_Bf_Processed`, `O_Bf_Raw`; well ID = `fname.split('_')[3]`; confluence % from `confluence_data.csv`.
- Get raw bytes via Mode A `aws s3`/`boto3` in the kernel, or Mode B `download_s3_prefix` on the
  narrowed `Images/` prefix; host the download and use its URL in the card (see the template §4 grid).
Prompt the user before doing the (optional) image pull.

---

## STEP 9 -- Session wrap-up

1. Update README/session notes (date + goal).
2. (Mode A) Update Session State: last/next step, kernel ID, files, quirks.
3. **Verify expected output files persisted to SAVE_DIR** (warn loudly for any missing — only those
   for the chosen DATA_OP are required):
   - STEP 2: `wells_metadata.csv`
   - STEP 3: `run_log_events.csv` *(options 1 & 2)*; `order_timeline.csv`, `imaging_timestamps.csv`, `seeding_order.csv` *(confluence)*
   - STEP 4: `confluence_data.csv` *(confluence)*
   - STEP 4Q: `qpcr_data.csv` *(qPCR)*
   - STEP 5: `qc_summary.csv`; `qpcr_knockdown_clean.csv`, `qpcr_doseresponse_clean.csv`, `qpcr_potency_clean.csv` *(qPCR DRC)*
   - STEP 6.5: `qc_verification.csv` (the independent recompute audit) — and confirm its verdict was **PASS**
   - STEP 6/7: figures and the `<screen>_<celltype>_<DRC>_<N>plates_<seeddate>.html` report (e.g. `MASH3_3T3_3pt_6plates_2026Jul8.html`; built from `assets/report_template.html`)
   `imaging_timestamps.csv` is the barcode→S3-folder map STEP 8 depends on — if absent, re-run STEP 3.
4. Report: plate count, assay design, readout(s), PASS/FLAG/FAIL counts, **QC-verification verdict**, notable findings.
