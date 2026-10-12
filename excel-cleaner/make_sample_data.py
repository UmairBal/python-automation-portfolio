"""
Creates realistic *messy* sales files in the input/ folder so the
cleaner has something to work on. Run this once before clean_report.py.

The mess is deliberate and typical of real exports:
  - several files that need merging
  - duplicate rows (same sale exported twice)
  - blank rows
  - mixed date formats
  - inconsistent city names (case, extra spaces)
  - amounts written as "$1,200", "1200", "1.1k", "n/a"
"""

import csv
import random
from pathlib import Path

random.seed(7)  # same data every run, so screenshots are repeatable

INPUT = Path(__file__).parent / "input"
INPUT.mkdir(exist_ok=True)

CITIES = ["Karachi", "Lahore", "Islamabad", "Multan", "Faisalabad", "Peshawar"]
PRODUCTS = ["Laptop", "Monitor", "Keyboard", "Mouse", "Printer", "Router"]
PRICES = {"Laptop": 650, "Monitor": 180, "Keyboard": 25, "Mouse": 12, "Printer": 140, "Router": 45}


def messy_date(year, month, day):
    """Write the same date in one of several inconsistent formats."""
    styles = [
        f"{year}-{month:02d}-{day:02d}",
        f"{day:02d}/{month:02d}/{year}",
        f"{day:02d}-{month:02d}-{year}",
        f"{year}/{month:02d}/{day:02d}",
        f"{day} {['Jan','Feb','Mar'][month-1]} {year}",
    ]
    return random.choice(styles)


def messy_city(city):
    return random.choice([city, city.lower(), city.upper(), f" {city}", f"{city} "])


def messy_amount(value):
    choices = [f"{value}", f"${value:,}", f"{value:.2f}", f"USD {value}"]
    if value >= 1000:
        choices.append(f"{value/1000:g}k")  # e.g. 1.95k
    return random.choice(choices)


order_id = 1000
for month, name in [(1, "jan"), (2, "feb"), (3, "mar")]:
    rows = []
    for _ in range(40):
        order_id += 1
        product = random.choice(PRODUCTS)
        qty = random.randint(1, 4)
        rows.append([
            f"ORD-{order_id}",
            messy_date(2026, month, random.randint(1, 28)),
            messy_city(random.choice(CITIES)),
            product,
            qty,
            messy_amount(PRICES[product] * qty),
        ])

    # Inject typical problems
    for _ in range(4):                       # duplicates
        rows.append(list(random.choice(rows)))
    for _ in range(2):                       # blank rows
        rows.insert(random.randint(0, len(rows)), ["", "", "", "", "", ""])
    rows[random.randint(0, 20)][5] = "n/a"   # missing amount
    random.shuffle(rows)

    with open(INPUT / f"sales_{name}_2026.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order ID", "Date", "City", "Product", "Qty", "Amount"])
        w.writerows(rows)

print(f"Created 3 messy files in {INPUT}")
