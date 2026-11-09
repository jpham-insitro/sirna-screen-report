"""
Parse SparkCyto confluence XLSX exports (FIM sheet) into a tidy long-format table.

*** This is the XLSX FALLBACK parser. The PREFERRED path is the XML export --
see scripts/parse_confluence_xml.py. MCP `read_s3_file` returns UTF-8 text only,
so the binary XLSX cannot be read in environments without an `aws` CLI / boto3.
Use this only if the XML is unavailable AND binary reads work. ***

Why this is bundled instead of left as prose in SKILL.md: Step 4 of the skill used
to say "if >12 files, write a parser to /tmp/parse_confluence.py" -- i.e. it told
every future run to reinvent this from scratch. That's the exact "repeated work
across runs" signal that should be fixed by writing the parser once and reusing it.

LAYOUT (confirmed against the BAT-1 DRC 3T3 3pt Jun24 run, 2026-07-01):
  - The confluence grid lives on the "FIM sheet", which is the **second tab** of
    the workbook. We prefer a sheet whose name contains "FIM"; if none matches we
    fall back to the second tab (index 1).
  - Somewhere in column A there is a row whose value **ends with**
    "Confluence [%]". The prefix varies by acquisition method -- e.g.
    "Brightfield_ConfluenceArea_96PE Confluence [%]" or
    "Brightfield_Segmentation_96PE Confluence [%]" -- so we anchor on the
    suffix, not a hardcoded full string. NOTE: an image-thumbnail grid with the
    same label sits ABOVE the numeric grid (~row 37), so we take the LAST such
    anchor row, whose following rows contain numbers.
  - The row immediately below the anchor is a header row with "<>" in column A
    and column labels 1-12 across the row (the 96-well plate columns).
  - The 8 rows immediately below the header are the well data rows, in order
    A-H, with the well's data value in the column matching cols 1-12 above.

Usage:
    python parse_confluence.py \\
        --input /path/to/plateA_T1.xlsx plate_id=PE4002160 timepoint=T1 \\
        --input /path/to/plateA_T2.xlsx plate_id=PE4002160 timepoint=T2 \\
        --output /SAVE_DIR/confluence_data.csv

Output is CSV by default (source of truth -- no pyarrow in the sandbox, parquet
may not round-trip). If --output ends in .parquet it will attempt parquet.

Each --input takes the XLSX path followed by key=value metadata pairs that get
attached to every row parsed from that file (plate_id and timepoint are required
since they generally aren't reliably recoverable from the filename alone).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ANCHOR_SUFFIX = "Confluence [%]"
HEADER_MARKER = "<>"
ROW_LETTERS = "ABCDEFGH"


def _find_sheet_name(xlsx_path: Path) -> str:
    xl = pd.ExcelFile(xlsx_path)
    candidates = [name for name in xl.sheet_names if "fim" in name.lower()]
    if candidates:
        return candidates[0]
    # Fallback: the FIM sheet is the second tab.
    if len(xl.sheet_names) >= 2:
        return xl.sheet_names[1]
    raise ValueError(
        f"{xlsx_path}: no 'FIM' sheet and fewer than 2 tabs "
        f"(sheets present: {xl.sheet_names}). Confirm the tab layout."
    )


def _parse_one_sheet(xlsx_path: Path, sheet_name: str) -> pd.DataFrame:
    raw = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)

    col_a = raw[0].astype(str).str.strip()
    anchor_rows = raw.index[col_a.str.endswith(ANCHOR_SUFFIX, na=False)]
    if len(anchor_rows) == 0:
        raise ValueError(
            f"{xlsx_path} [{sheet_name}]: couldn't find a column-A cell ending in "
            f"{ANCHOR_SUFFIX!r}. The export layout may have changed -- inspect the "
            "file manually before patching this parser."
        )
    # A same-labeled image-thumbnail grid sits above the numeric grid; take the
    # LAST anchor so we land on the numeric block.
    anchor_idx = anchor_rows[-1]

    header_idx = anchor_idx + 1
    header_val = str(raw.iat[header_idx, 0])
    if HEADER_MARKER not in header_val:
        raise ValueError(
            f"{xlsx_path} [{sheet_name}]: expected '{HEADER_MARKER}' in column A "
            f"of the row right after the anchor (row {header_idx}), found "
            f"{header_val!r} instead. Layout assumption may be wrong."
        )

    # Column labels 1-12 are read from the header row itself.
    col_labels = raw.iloc[header_idx, 1:13]
    try:
        col_labels = [int(c) for c in col_labels]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{xlsx_path} [{sheet_name}]: header row columns 1-12 didn't parse "
            f"as integers ({col_labels.tolist()!r}) -- check layout."
        ) from exc

    records = []
    for i, row_letter in enumerate(ROW_LETTERS):
        data_idx = header_idx + 1 + i
        if data_idx >= len(raw):
            raise ValueError(
                f"{xlsx_path} [{sheet_name}]: ran out of rows before reaching "
                f"well row {row_letter} -- expected 8 data rows (A-H) after the "
                "header."
            )
        row_vals = raw.iloc[data_idx, 1:13]
        well_row = i + 1  # gotcha: well_row is int 1-8, not the letter
        for col_label, val in zip(col_labels, row_vals):
            records.append(
                {
                    "well_row": well_row,
                    "well_column": int(col_label),  # gotcha: keep as int, not str
                    "confluence_pct": float(val) if pd.notna(val) else None,
                }
            )
    return pd.DataFrame.from_records(records)


def parse_file(xlsx_path: Path, metadata: dict) -> pd.DataFrame:
    sheet_name = _find_sheet_name(xlsx_path)
    df = _parse_one_sheet(xlsx_path, sheet_name)
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
            "these aren't reliably inferable from the filename, don't guess."
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
        help="XLSX path followed by plate_id=... timepoint=... (repeatable)",
    )
    parser.add_argument(
        "--output", required=True, help="output path (.csv preferred; .parquet optional)"
    )
    args = parser.parse_args(argv)

    frames = []
    for tokens in args.input:
        path, metadata = _parse_input_arg(tokens)
        print(f"Parsing {path} ({metadata}) ...", file=sys.stderr)
        frames.append(parse_file(path, metadata))

    out = pd.concat(frames, ignore_index=True)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".parquet":
        out.to_parquet(out_path, index=False)
    else:
        out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
