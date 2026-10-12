"""
Excel / CSV cleaning and report automation.

Merges every .csv and .xlsx file in the input/ folder, cleans the data,
and writes one formatted Excel report to output/sales_report.xlsx.

Cleaning steps:
  1. Merge all files and remember which file each row came from
  2. Drop fully blank rows
  3. Remove duplicate orders (same Order ID)
  4. Standardise dates to YYYY-MM-DD (handles mixed formats)
  5. Standardise city names (trim spaces, fix capitalisation)
  6. Convert amounts like "$1,200", "1.1k", "USD 640" to numbers
  7. Flag rows that still have problems instead of silently deleting them

Usage:
    python clean_report.py
    python clean_report.py --input my_folder --output my_report.xlsx
"""

import argparse
import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent


# ---------- loading ----------

def load_files(folder: Path) -> pd.DataFrame:
    """Read every CSV/XLSX file in the folder into one table."""
    frames = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        elif path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(path, dtype=str).fillna("")
        else:
            continue
        df["Source File"] = path.name
        frames.append(df)

    if not frames:
        raise SystemExit(f"No .csv or .xlsx files found in {folder}")
    return pd.concat(frames, ignore_index=True)


# ---------- cleaning helpers ----------

def parse_date(value: str):
    """Try day-first, then year-first, so 03/01/2026 means 3 January."""
    value = str(value).strip()
    if not value:
        return pd.NaT
    yearfirst = bool(re.match(r"^\d{4}", value))
    return pd.to_datetime(value, dayfirst=not yearfirst, yearfirst=yearfirst, errors="coerce")


def parse_amount(value: str):
    """Turn '$1,200', '1.1k', 'USD 640', '850.50' into a number; 'n/a' -> missing."""
    text = str(value).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    if not text or text in ("n/a", "na", "-", "none"):
        return None
    multiplier = 1000 if text.endswith("k") else 1
    text = text.rstrip("k")
    try:
        return round(float(text) * multiplier, 2)
    except ValueError:
        return None


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = {"rows_in": len(df), "files": df["Source File"].nunique()}

    # 1. blank rows (every data column empty)
    data_cols = [c for c in df.columns if c != "Source File"]
    blank = df[data_cols].apply(lambda r: all(str(v).strip() == "" for v in r), axis=1)
    df = df[~blank].copy()
    stats["blank_removed"] = int(blank.sum())

    # 2. duplicates by Order ID
    before = len(df)
    df["Order ID"] = df["Order ID"].str.strip()
    df = df.drop_duplicates(subset="Order ID", keep="first")
    stats["duplicates_removed"] = before - len(df)

    # 3. dates, cities, quantities, amounts
    df["Date"] = df["Date"].apply(parse_date)
    df["City"] = df["City"].str.strip().str.title()
    df["Product"] = df["Product"].str.strip().str.title()
    df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").astype("Int64")
    df["Amount"] = df["Amount"].apply(parse_amount)

    # 4. flag anything still wrong, so a human can check it
    issues = []
    for _, row in df.iterrows():
        problems = []
        if pd.isna(row["Date"]):
            problems.append("bad date")
        if pd.isna(row["Amount"]):
            problems.append("missing amount")
        issues.append(", ".join(problems))
    df["Check"] = issues
    stats["flagged"] = int((df["Check"] != "").sum())

    df = df.sort_values("Date").reset_index(drop=True)
    stats["rows_out"] = len(df)
    return df, stats


# ---------- report ----------

HEADER_FILL = PatternFill("solid", fgColor="1F6F43")
TOTAL_FILL = PatternFill("solid", fgColor="DDEBE2")
FLAG_FILL = PatternFill("solid", fgColor="FDE2E1")
WHITE_BOLD = Font(bold=True, color="FFFFFF")


def style_sheet(ws, money_cols=(), flag_col=None):
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = WHITE_BOLD
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for col_idx, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row), start=1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(width + 3, 10), 40)
        header = col[0].value
        if header in money_cols:
            for c in col[1:]:
                c.number_format = '"$"#,##0.00'
        if header == "Date":
            for c in col[1:]:
                c.number_format = "yyyy-mm-dd"

    if flag_col:
        idx = [c.value for c in ws[1]].index(flag_col) + 1
        for row in ws.iter_rows(min_row=2):
            if row[idx - 1].value:
                for c in row:
                    c.fill = FLAG_FILL


def write_report(df: pd.DataFrame, stats: dict, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary = (df.groupby("City", as_index=False)
                 .agg(Orders=("Order ID", "count"), Units=("Qty", "sum"), Revenue=("Amount", "sum"))
                 .sort_values("Revenue", ascending=False))
    monthly = (df.dropna(subset=["Date"])
                 .assign(Month=lambda d: d["Date"].dt.strftime("%Y-%m"))
                 .groupby("Month", as_index=False)
                 .agg(Orders=("Order ID", "count"), Revenue=("Amount", "sum")))

    cols = ["Order ID", "Date", "City", "Product", "Qty", "Amount", "Source File", "Check"]
    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        df[cols].to_excel(xw, sheet_name="Clean Data", index=False)
        summary.to_excel(xw, sheet_name="By City", index=False)
        monthly.to_excel(xw, sheet_name="By Month", index=False)

        log = pd.DataFrame({
            "Step": ["Files merged", "Rows read", "Blank rows removed", "Duplicate orders removed",
                     "Rows flagged for review", "Clean rows"],
            "Value": [stats["files"], stats["rows_in"], stats["blank_removed"],
                      stats["duplicates_removed"], stats["flagged"], stats["rows_out"]],
        })
        log.to_excel(xw, sheet_name="Cleaning Log", index=False)

        style_sheet(xw.sheets["Clean Data"], money_cols=("Amount",), flag_col="Check")
        style_sheet(xw.sheets["By City"], money_cols=("Revenue",))
        style_sheet(xw.sheets["By Month"], money_cols=("Revenue",))
        style_sheet(xw.sheets["Cleaning Log"])

        # totals row on the city summary
        ws = xw.sheets["By City"]
        r = ws.max_row + 1
        ws.cell(r, 1, "TOTAL")
        for col in (2, 3, 4):
            letter = get_column_letter(col)
            ws.cell(r, col, f"=SUM({letter}2:{letter}{r-1})")
        ws.cell(r, 4).number_format = '"$"#,##0.00'
        for col in range(1, 5):
            ws.cell(r, col).fill = TOTAL_FILL
            ws.cell(r, col).font = Font(bold=True)


def main():
    ap = argparse.ArgumentParser(description="Merge and clean sales files into one Excel report.")
    ap.add_argument("--input", default=HERE / "input", type=Path)
    ap.add_argument("--output", default=HERE / "output" / "sales_report.xlsx", type=Path)
    args = ap.parse_args()

    raw = load_files(args.input)
    df, stats = clean(raw)
    write_report(df, stats, args.output)

    print(f"Merged {stats['files']} files, {stats['rows_in']} rows")
    print(f"  removed {stats['blank_removed']} blank rows and {stats['duplicates_removed']} duplicates")
    print(f"  flagged {stats['flagged']} rows for review")
    print(f"Report saved to {args.output}  ({stats['rows_out']} clean rows)")


if __name__ == "__main__":
    main()
