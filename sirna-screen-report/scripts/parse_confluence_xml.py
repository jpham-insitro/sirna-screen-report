"""
Parse SparkCyto AutomationInterfaceExport.xml into a tidy long-format confluence table.

*** This is the PREFERRED confluence path. ***
MCP `read_s3_file` returns UTF-8 text only, so the binary XLSX cannot be read in
environments with no `aws` CLI / boto3. The XML export is plain text and can be
read directly, so it is the default route. Use scripts/parse_confluence.py only as
an XLSX fallback.

WHERE THE XML LIVES (see STEP 3/4 of SKILL.md):
  s3://insitro-microscopy-spark-cyto-archive/<INSTRUMENT>/<Method>_<localYYYYMMDD_HHMMSS>_<barcode>/Export/xml/AutomationInterfaceExport.xml
  - barcode is a SUFFIX on the workspace-folder name.
  - folder timestamp is LOCAL (PDT = UTC-7); the Cellario_Drivers.log timestamp is UTC.

WHAT WE PARSE (confirmed against the BAT-1 DRC 3T3 3pt Jun24 run, 2026-07-01):
  - Each per-well result is a `<ResultContext ...>` block.
  - The well label comes from the image filename token `_96PE_<row><col>_`
    (row = A-H, col = 1-12) -- this is ROBUST; do NOT rely on WellIndex ordering.
  - The confluent (segmented) area per well is the scalar `TotalAreaInUm2`.
    There is NO literal "Confluence" scalar in the XML -- only TotalAreaInUm2 and
    RoughnessFactor.
  - Confluence % = TotalAreaInUm2 / well_area * 100.
    well_area = pi * r**2. A 6.4 mm-bottom Revvity/PerkinElmer 96-well
    (CellCarrier / PhenoPlate) => 3.217e7 um^2 (the default below).
    %CV is INDEPENDENT of this denominator (ratio metric); only the absolute
    mean-confluence threshold depends on it. State the denominator in the report.

The parser raises a clear error rather than silently mis-parsing if a per-file
assumption doesn't hold (no ResultContext blocks, no well token, no area value).

Usage (one --input per plate x timepoint; XML already fetched to a local path):
    python parse_confluence_xml.py \\
        --input /path/plateA_T1.xml plate_id=PE4002160 timepoint=T1 \\
        --input /path/plateA_T2.xml plate_id=PE4002160 timepoint=T2 \\
        --output /SAVE_DIR/confluence_data.csv

Output columns: plate_id, well_row (1-8), well_column (1-12), well_label,
timepoint, total_area_um2, confluence_pct  (+ any extra key=value metadata).
CSV is the source of truth (no pyarrow in the sandbox; parquet may not round-trip).
Pass --well-area-um2 to override the denominator for a different plate format.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

# 6.4 mm-bottom 96-well: pi * (3200 um)^2 ~= 3.217e7 um^2
DEFAULT_WELL_AREA_UM2 = math.pi * (6400.0 / 2.0) ** 2  # ~= 3.217e7

WELL_TOKEN_RE = re.compile(r"_96PE_([A-H])(\d{1,2})_")
# Match TotalAreaInUm2 whether it's an attribute (Value="...") or an element body.
AREA_RE = re.compile(
    r"TotalAreaInUm2\D{0,40}?(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)


def _localname(tag: str) -> str:
    """Strip any XML namespace so we can match ResultContext regardless of ns."""
    return tag.rsplit("}", 1)[-1]


def _iter_result_contexts(root: ET.Element):
    for el in root.iter():
        if _localname(el.tag) == "ResultContext":
            yield el


def _block_text(el: ET.Element) -> str:
    """Serialize an element (attributes + descendants) to a searchable string."""
    return ET.tostring(el, encoding="unicode")


def _parse_one_xml(xml_path: Path) -> pd.DataFrame:
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(
            f"{xml_path}: not well-formed XML ({exc}). Confirm you fetched the "
            "AutomationInterfaceExport.xml text, not a truncated/binary blob."
        ) from exc

    blocks = list(_iter_result_contexts(root))
    if not blocks:
        raise ValueError(
            f"{xml_path}: no <ResultContext> blocks found. The export schema may "
            "have changed -- inspect the XML before patching this parser."
        )

    records = []
    for el in blocks:
        chunk = _block_text(el)

        well_match = WELL_TOKEN_RE.search(chunk)
        if not well_match:
            # A ResultContext without a _96PE_<row><col>_ token isn't a well result
            # (e.g. a plate-level summary block); skip it rather than guessing.
            continue
        row_letter, col_str = well_match.group(1), well_match.group(2)
        well_column = int(col_str)
        if not (1 <= well_column <= 12):
            raise ValueError(
                f"{xml_path}: parsed well column {well_column} out of range 1-12 "
                f"from token {well_match.group(0)!r} -- check the filename pattern."
            )
        well_row = ord(row_letter) - ord("A") + 1  # 1-8, int (gotcha: not a letter)

        area_match = AREA_RE.search(chunk)
        if not area_match:
            raise ValueError(
                f"{xml_path}: found well {row_letter}{well_column} but no "
                "TotalAreaInUm2 value nearby. Layout assumption may be wrong -- "
                "inspect the ResultContext block manually."
            )
        total_area = float(area_match.group(1))

        records.append(
            {
                "well_row": well_row,
                "well_column": well_column,  # gotcha: keep int, not str
                "well_label": f"{row_letter}{well_column}",
                "total_area_um2": total_area,
            }
        )

    if not records:
        raise ValueError(
            f"{xml_path}: ResultContext blocks present but none had a "
            "_96PE_<row><col>_ well token -- filename convention may have changed."
        )
    return pd.DataFrame.from_records(records)


def parse_file(xml_path: Path, metadata: dict, well_area_um2: float) -> pd.DataFrame:
    df = _parse_one_xml(xml_path)
    df["confluence_pct"] = df["total_area_um2"] / well_area_um2 * 100.0
    for key, val in metadata.items():
        df[key] = val
    return df


def _parse_input_arg(tokens: list[str]) -> tuple[Path, dict]:
    if not tokens:
        raise argparse.ArgumentTypeError("--input requires a file path")
    path = Path(tokens[0])
    metadata = {}
    for tok in tokens[1:]:
        if "=" not in tok:
            raise argparse.ArgumentTypeError(
                f"expected key=value metadata, got {tok!r}"
            )
        key, val = tok.split("=", 1)
        metadata[key] = val
    if "plate_id" not in metadata or "timepoint" not in metadata:
        raise argparse.ArgumentTypeError(
            f"{path}: must supply plate_id=... and timepoint=... metadata -- "
            "these aren't reliably inferable from the path, don't guess."
        )
    return path, metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        nargs="+",
        action="append",
        required=True,
        metavar="PATH key=value [key=value ...]",
        help="XML path followed by plate_id=... timepoint=... (repeatable)",
    )
    parser.add_argument(
        "--output", required=True, help="output path (.csv preferred; .parquet optional)"
    )
    parser.add_argument(
        "--well-area-um2",
        type=float,
        default=DEFAULT_WELL_AREA_UM2,
        help=f"well-bottom area denominator (default {DEFAULT_WELL_AREA_UM2:.3e} "
        "for a 6.4 mm 96-well)",
    )
    args = parser.parse_args(argv)

    frames = []
    for tokens in args.input:
        path, metadata = _parse_input_arg(tokens)
        print(f"Parsing {path} ({metadata}) ...", file=sys.stderr)
        frames.append(parse_file(path, metadata, args.well_area_um2))

    out = pd.concat(frames, ignore_index=True)
    # Stable, human-readable column order.
    lead = [
        "plate_id",
        "well_row",
        "well_column",
        "well_label",
        "timepoint",
        "total_area_um2",
        "confluence_pct",
    ]
    cols = [c for c in lead if c in out.columns] + [
        c for c in out.columns if c not in lead
    ]
    out = out[cols]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".parquet":
        out.to_parquet(out_path, index=False)
    else:
        out.to_csv(out_path, index=False)
    print(
        f"Wrote {len(out)} rows to {out_path} "
        f"(well_area={args.well_area_um2:.4e} um^2)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
