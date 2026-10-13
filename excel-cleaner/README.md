# Excel Data Cleaning & Report Automation

Merges every CSV/Excel file in `input/`, cleans the data and writes one formatted report.

**What it fixes:** duplicate orders, blank rows, mixed date formats, inconsistent city names,
amounts written as `$1,300`, `1.95k`, `USD 140`. Rows it can't fix (e.g. missing amount)
are highlighted for review instead of being silently deleted.

**Output (`output/sales_report.xlsx`):** Clean Data · By City (with totals) · By Month · Cleaning Log

## Run
```
pip install pandas openpyxl
python make_sample_data.py   # creates messy sample files in input/
python clean_report.py       # builds output/sales_report.xlsx
```
Use your own files: `python clean_report.py --input path/to/folder --output report.xlsx`

## Screenshots

![Cleaned sales report](screenshots/excel-cleaner.png)
