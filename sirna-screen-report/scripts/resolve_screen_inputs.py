"""
resolve_screen_inputs.py
========================

Readout-agnostic input resolver for the `sirna-screen-report` skill.

WHY THIS EXISTS
---------------
Today the skill is driven by **plate IDs** (PE40XXXXXX). Scientists usually think
in terms of a *project* or a *screen*, not a list of barcodes. This module lets the
skill start from ANY of:

    * a project code   -- "PRJ087"                      (Benchling registry id)
    * a project name   -- "Adiposity Discovery"         (free-text, fuzzy)
    * one/many plate IDs -- "PE4002160", "PE4002161"    (PE barcodes)

...and fan out to the full plate set + the data-source locations for BOTH readouts
the skill supports:

    * confluence QC   -- SparkCyto archives (existing STEP 3/4 of the skill)
    * qPCR knockdown  -- the `qpcr_well_measurements` index (Cq / ddCt / knockdown%,
                         already computed) + the raw QuantStudio CSV on S3

CONCEPT -> CODE MAP (insitro-index fields verified 2026-07-09)
-------------------------------------------------------------
projects index:
    id / benchling_id  == "PRJ###"   <-- match a PRJ token HERE (NOT project_code)
    project_code       == short code e.g. "2004"  (a different identifier)
    name               == human name e.g. "Pipeline - Adiposity Discovery"
    experiments[].name == "EINS##### - PRJ### - <desc>"
    campaigns[].id/.name, campaigns[].activities[].id (CACT###)

plates index:
    barcode / barcode_raw       == "PE4002160"
    experiments[].name          == "EINS11504 - PRJ087 - BAT-1_DRC screen ..."
    experiments[].project       == "Pipeline - Adiposity Discovery"  (project name)
    cell_line_instances[].cell_line_name / .cell_line_registry_id (Cins####)
    wells[].barcode             == "PE4002160:A1"

qpcr_well_measurements index (one doc == one source well x plate):
    source_plate_id             == "PE4002160"
    experiment.name             == "EINS11504 - PRJ087 - ..."   (project via regex)
    qpcr_run.s3_bucket/.s3_key  == raw QuantStudio Result CSV location
    qpcr_run.processed_exports  == [run_wells.csv, pivot.csv] (insitro-scratch)
    target_gene / housekeeping_gene, delta_ct, delta_delta_ct, fold_change,
    mrna_remaining, knockdown_pct, compounds[], cell_line_instances[]

EXECUTION MODES (mirror the skill's Mode A / Mode B)
----------------------------------------------------
This module does NO I/O of its own. You inject a `search_index(index, query, size,
filter)` callable so the same logic runs in either environment and is unit-testable:

    Mode A (kernel):     bind `search_index` to an insitro-index HTTP client, or wrap
                         a warehouse SQL query.
    Mode B (Cowork):     Claude performs the `search_index` MCP calls described in each
                         docstring and feeds results back; this module is the spec.

ANTICIPATORY ERROR-CHECKING (stated up front, per lab convention)
-----------------------------------------------------------------
* If a "PRJ###" token is matched against `project_code`, this WILL return nothing
  (PRJ lives in `id`). Mitigation: `classify_input` routes PRJ tokens to the `id`
  match path; verified against PRJ087 -> id="PRJ087", project_code="2004".
* If a project name is ambiguous (>1 hit), this WILL silently pick the wrong project.
  Mitigation: `resolve_project` returns ALL candidates and raises `AmbiguousProject`
  rather than guessing -- the caller must disambiguate.
* If a plate has no qPCR run, requesting readout="qpcr" WILL yield an empty frame.
  Mitigation: `qpcr_sources_for_plate` sets `has_qpcr=False`; caller reports the gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
# A search_index callable: (index_name, query, size, filter) -> list[dict]
# Return the list at result.results (already unwrapped from the MCP envelope).
SearchFn = Callable[..., list]

PRJ_RE = re.compile(r"\bPRJ\d+\b", re.IGNORECASE)
EINS_RE = re.compile(r"\bEINS\d+\b", re.IGNORECASE)
CACT_RE = re.compile(r"\bCACT\d+\b", re.IGNORECASE)
# Plate barcodes at insitro follow P<letter>#######, e.g. PE4002160 / PA20712.
PLATE_RE = re.compile(r"\bP[A-Z]\d{4,}\b")


class AmbiguousProject(Exception):
    """Raised when a project-name query matches more than one project."""


class UnresolvedInput(Exception):
    """Raised when an input token cannot be classified or resolved."""


@dataclass
class QpcrSource:
    """Per-plate qPCR data-source pointers + headline computed metrics."""
    has_qpcr: bool = False
    raw_csv_s3: Optional[str] = None          # s3://<bucket>/<key> QuantStudio Result CSV
    processed_exports: list = field(default_factory=list)  # run_wells.csv / pivot.csv
    target_genes: list = field(default_factory=list)
    housekeeping_genes: list = field(default_factory=list)
    n_wells: int = 0


@dataclass
class PlateRecord:
    barcode: str
    benchling_id: Optional[str] = None
    project_code: Optional[str] = None        # PRJ### parsed from experiment name
    project_name: Optional[str] = None
    experiment_id: Optional[str] = None        # EINS#####
    campaign_id: Optional[str] = None          # CACT### (if resolvable)
    cell_line_name: Optional[str] = None
    cell_line_registry_id: Optional[str] = None
    qpcr: QpcrSource = field(default_factory=QpcrSource)


@dataclass
class ResolvedScreen:
    input_kind: str                            # 'project_code' | 'project_name' | 'plate_id'
    project_code: Optional[str] = None         # PRJ###
    project_name: Optional[str] = None
    plates: list = field(default_factory=list)  # list[PlateRecord]

    @property
    def barcodes(self) -> list:
        return [p.barcode for p in self.plates]

    @property
    def qpcr_plates(self) -> list:
        return [p for p in self.plates if p.qpcr.has_qpcr]


# ---------------------------------------------------------------------------
# 1. Classify the input token
# ---------------------------------------------------------------------------
def classify_input(token: str) -> str:
    """Decide whether `token` is a project code, plate id, or project name.

    Order matters: PRJ and plate patterns are unambiguous; anything else is
    treated as a free-text project name.
    """
    t = token.strip()
    if PRJ_RE.fullmatch(t) or PRJ_RE.match(t) and t.upper().startswith("PRJ"):
        return "project_code"
    if PLATE_RE.fullmatch(t):
        return "plate_id"
    return "project_name"


def _parse_project_from_experiment_name(name: str) -> Optional[str]:
    """Extract PRJ### from an experiment display name like
    'EINS11504 - PRJ087 - BAT-1_DRC screen...'. Returns None if absent."""
    if not name:
        return None
    m = PRJ_RE.search(name)
    return m.group(0).upper() if m else None


def _parse_eins(name: str) -> Optional[str]:
    m = EINS_RE.search(name or "")
    return m.group(0).upper() if m else None


# ---------------------------------------------------------------------------
# 2. Resolve a project (code or name) -> canonical project identity
# ---------------------------------------------------------------------------
def resolve_project(token: str, search_index: SearchFn) -> dict:
    """Resolve a project code (PRJ###) or free-text name to a single project.

    Queries the `projects` index. For a PRJ token we match on the `id` field
    (NOT `project_code`). For a name we fuzzy-match on `name` and REFUSE to guess
    if more than one project matches -- raising AmbiguousProject with candidates.

    Returns: {'project_code': 'PRJ###', 'project_name': str, 'benchling_id': str,
              'experiments': [...], 'campaigns': [...]}
    """
    kind = classify_input(token)
    hits = search_index(index="projects", query=token, size=25)

    if kind == "project_code":
        prj = token.strip().upper()
        exact = [h for h in hits if str(h.get("id", "")).upper() == prj
                 or str(h.get("benchling_id", "")).upper() == prj]
        if not exact:
            raise UnresolvedInput(f"No project with id == {prj} (checked `id`, not `project_code`).")
        chosen = exact[0]
    else:  # project_name -- fuzzy
        needle = token.strip().lower()
        cand = [h for h in hits if needle in str(h.get("name", "")).lower()]
        if not cand:
            raise UnresolvedInput(f"No project whose name contains {token!r}.")
        if len(cand) > 1:
            names = [f"{h.get('id')} :: {h.get('name')}" for h in cand]
            raise AmbiguousProject(
                f"{len(cand)} projects match {token!r}; disambiguate:\n  " + "\n  ".join(names)
            )
        chosen = cand[0]

    return {
        "project_code": chosen.get("id") or chosen.get("benchling_id"),
        "project_name": chosen.get("name"),
        "benchling_id": chosen.get("benchling_id"),
        "experiments": chosen.get("experiments", []) or [],
        "campaigns": chosen.get("campaigns", []) or [],
    }


# ---------------------------------------------------------------------------
# 3. Project -> plate set  (union across readouts, deduped)
# ---------------------------------------------------------------------------
def plates_for_project(project_code: str, search_index: SearchFn,
                       include_qpcr: bool = True) -> list:
    """Return the deduped list of plate barcodes belonging to a project.

    Two complementary sources are unioned:
      (a) `plates` index  -- every registered plate whose experiment name carries
          the PRJ code (covers confluence-only plates).
      (b) `qpcr_well_measurements` -- source_plate_ids seen in qPCR runs for the
          project (covers plates that produced qPCR but might index differently).

    Union + dedup so neither readout is missed. Full-text query on the PRJ code
    matches the embedded experiment name in both indices.
    """
    barcodes: set = set()

    for h in search_index(index="plates", query=project_code, size=200):
        bc = h.get("barcode") or h.get("barcode_raw")
        # Guard: only keep plates whose experiment name actually carries this PRJ,
        # since full-text can over-match.
        exps = h.get("experiments", []) or []
        if bc and any(_parse_project_from_experiment_name(e.get("name", "")) ==
                      project_code.upper() for e in exps):
            barcodes.add(bc)

    if include_qpcr:
        for h in search_index(index="qpcr_well_measurements", query=project_code, size=500):
            bc = h.get("source_plate_id")
            exp = (h.get("experiment") or {}).get("name", "")
            if bc and _parse_project_from_experiment_name(exp) == project_code.upper():
                barcodes.add(bc)

    return sorted(barcodes)


# ---------------------------------------------------------------------------
# 4. Plate -> metadata + per-readout data sources
# ---------------------------------------------------------------------------
def qpcr_sources_for_plate(barcode: str, search_index: SearchFn) -> QpcrSource:
    """Locate qPCR data for one plate via `qpcr_well_measurements`.

    Sets has_qpcr=False (not an error) when the plate has no qPCR run -- the
    caller decides whether that gap matters for the requested readout.
    """
    rows = search_index(index="qpcr_well_measurements", query=barcode, size=500)
    rows = [r for r in rows if r.get("source_plate_id") == barcode]
    if not rows:
        return QpcrSource(has_qpcr=False)

    run = rows[0].get("qpcr_run", {}) or {}
    bucket, key = run.get("s3_bucket"), run.get("s3_key")
    raw = f"s3://{bucket}/{key}" if bucket and key else None
    targets = sorted({r.get("target_gene") for r in rows if r.get("target_gene")})
    hks = sorted({r.get("housekeeping_gene") for r in rows if r.get("housekeeping_gene")})

    return QpcrSource(
        has_qpcr=True,
        raw_csv_s3=raw,
        processed_exports=run.get("processed_exports", []) or [],
        target_genes=targets,
        housekeeping_genes=hks,
        n_wells=len(rows),
    )


def resolve_plate(barcode: str, search_index: SearchFn,
                  want_qpcr: bool = True) -> PlateRecord:
    """Build a PlateRecord (identity + readout sources) for one barcode."""
    hits = [h for h in search_index(index="plates", query=barcode, size=5)
            if (h.get("barcode") or h.get("barcode_raw")) == barcode]
    rec = PlateRecord(barcode=barcode)
    if hits:
        h = hits[0]
        rec.benchling_id = h.get("benchling_id")
        exps = h.get("experiments", []) or []
        if exps:
            rec.project_name = exps[0].get("project")
            rec.project_code = _parse_project_from_experiment_name(exps[0].get("name", ""))
            rec.experiment_id = _parse_eins(exps[0].get("name", ""))
        clis = h.get("cell_line_instances", []) or []
        if clis:
            rec.cell_line_name = clis[0].get("cell_line_name")
            rec.cell_line_registry_id = clis[0].get("cell_line_registry_id")

    if want_qpcr:
        rec.qpcr = qpcr_sources_for_plate(barcode, search_index)
        # Backfill project identity from qPCR experiment if plates index was thin.
        if not rec.project_code and rec.qpcr.has_qpcr:
            qrows = [r for r in search_index(index="qpcr_well_measurements",
                                             query=barcode, size=1)]
            if qrows:
                exp = (qrows[0].get("experiment") or {}).get("name", "")
                rec.project_code = _parse_project_from_experiment_name(exp)
                rec.experiment_id = _parse_eins(exp)
    return rec


# ---------------------------------------------------------------------------
# 5. Top-level entry point
# ---------------------------------------------------------------------------
def resolve_screen(inputs, search_index: SearchFn,
                   want_qpcr: bool = True) -> ResolvedScreen:
    """Resolve a screen from a project code, project name, or one/many plate IDs.

    `inputs` may be a single string or a list. Mixed lists are allowed but should
    share a single kind in practice (e.g. several plate IDs).
    """
    if isinstance(inputs, str):
        inputs = [inputs]
    if not inputs:
        raise UnresolvedInput("No input provided.")

    kinds = {classify_input(t) for t in inputs}

    # --- Plate-id path -------------------------------------------------------
    if kinds == {"plate_id"}:
        plates = [resolve_plate(bc, search_index, want_qpcr) for bc in inputs]
        pcodes = {p.project_code for p in plates if p.project_code}
        pnames = {p.project_name for p in plates if p.project_name}
        return ResolvedScreen(
            input_kind="plate_id",
            project_code=next(iter(pcodes), None) if len(pcodes) == 1 else None,
            project_name=next(iter(pnames), None) if len(pnames) == 1 else None,
            plates=plates,
        )

    # --- Project path (code or name) ----------------------------------------
    if len(inputs) != 1:
        raise UnresolvedInput("Provide a single project code/name, or a list of plate IDs.")
    proj = resolve_project(inputs[0], search_index)
    barcodes = plates_for_project(proj["project_code"], search_index, include_qpcr=want_qpcr)
    plates = [resolve_plate(bc, search_index, want_qpcr) for bc in barcodes]
    return ResolvedScreen(
        input_kind=classify_input(inputs[0]),
        project_code=proj["project_code"],
        project_name=proj["project_name"],
        plates=plates,
    )


# ---------------------------------------------------------------------------
# Self-test (pure logic; mock search_index seeded with observed real records)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Minimal fixtures mirroring the live index docs observed on 2026-07-09.
    PROJECTS = [
        {"id": "PRJ087", "benchling_id": "PRJ087", "project_code": "2004",
         "name": "Pipeline - Adiposity Discovery",
         "experiments": [{"name": "EINS11504 - PRJ087 - BAT-1_DRC screen for 3T3 3pt"}]},
        {"id": "PRJ079", "benchling_id": "PRJ079", "project_code": "F000",
         "name": "No Project", "experiments": []},
    ]
    PLATES = [{"barcode": "PE4002160", "benchling_id": "plt_ZmNa6JlmaW",
               "experiments": [{"name": "EINS11504 - PRJ087 - BAT-1_DRC screen for 3T3 3pt",
                                "project": "Pipeline - Adiposity Discovery"}],
               "cell_line_instances": [{"cell_line_name": "3T3-L1",
                                        "cell_line_registry_id": "Cins3249"}]}]
    QPCR = [{"source_plate_id": "PE4002160", "target_gene": "FAM13A",
             "housekeeping_gene": "GAPDH",
             "experiment": {"name": "EINS11504 - PRJ087 - BAT-1_DRC screen for 3T3 3pt"},
             "qpcr_run": {"s3_bucket": "insitro-lab-equipment",
                          "s3_key": "042_QuantStudio-01/Max_Bates_qPCR/x_Result.csv",
                          "processed_exports": ["s3://insitro-scratch/.../pivot.csv"]}}]

    def fake_search(index, query, size=10, filter=None):
        q = str(query).lower()
        pool = {"projects": PROJECTS, "plates": PLATES, "qpcr_well_measurements": QPCR}[index]
        # crude full-text: keep docs whose serialized form contains the query
        return [d for d in pool if q in str(d).lower()]

    # 1. classification
    assert classify_input("PRJ087") == "project_code"
    assert classify_input("PE4002160") == "plate_id"
    assert classify_input("Adiposity Discovery") == "project_name"

    # 2. plate-id entry
    r1 = resolve_screen("PE4002160", fake_search)
    assert r1.barcodes == ["PE4002160"]
    assert r1.project_code == "PRJ087"
    assert r1.plates[0].qpcr.has_qpcr and r1.plates[0].qpcr.target_genes == ["FAM13A"]

    # 3. project-code entry
    r2 = resolve_screen("PRJ087", fake_search)
    assert "PE4002160" in r2.barcodes and r2.project_name == "Pipeline - Adiposity Discovery"

    # 4. project-name entry (unambiguous here)
    r3 = resolve_screen("Adiposity", fake_search)
    assert r3.project_code == "PRJ087"

    # 5. PRJ must NOT match on project_code (=2004)
    try:
        resolve_project("PRJ9999", fake_search); assert False
    except UnresolvedInput:
        pass

    print("resolve_screen_inputs self-test: ALL PASS")
