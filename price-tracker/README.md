# Price Tracker: History, Change Detection & Alerts

Collects live prices on every run, keeps the full history in a local SQLite
database, compares each run with the previous one, flags moves above a
threshold and rebuilds an Excel report with a price-history chart.

Data source: CoinGecko public API (free, no key needed for light use).
The same structure works for product prices scraped from any website.

**Report (`output/price_report.xlsx`):**
- **Latest** – current price, previous price and change; rises green, falls red
- **Alerts** – coins that moved more than the threshold since the last run
- **History** – every run, with a line chart of the top 5
- **Chart data** – prices indexed to 100 at the first run

## Run
```
pip install -r requirements.txt
python tracker.py                         # one run
python tracker.py --every 10 --runs 6     # every 10 minutes for an hour
python tracker.py --coins 15 --threshold 1.0
```

## Schedule it
- **Linux / Mac (cron, every 30 min):** `*/30 * * * * cd /path/to/price-tracker && python3 tracker.py`
- **Windows:** Task Scheduler → Create Basic Task → run `python tracker.py` in this folder
