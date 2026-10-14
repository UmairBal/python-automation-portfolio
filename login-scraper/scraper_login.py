"""
Login + multi-page scraper -> linked Excel report.

Logs into a site (handling the hidden CSRF token in the login form), walks
through every list page, then opens each author's detail page to collect
extra fields. Results are joined into one Excel workbook.

Target: https://quotes.toscrape.com  (public practice site; it accepts any
username and password, so no real account is needed)

Credentials are never hard-coded. Pass them as arguments or environment
variables:
    export SCRAPER_USER=demo
    export SCRAPER_PASS=demo
    python scraper_login.py

Options:
    --pages 2        limit list pages (quick test)
    --base URL       different base URL (e.g. a local test server)
"""

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = "https://quotes.toscrape.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio scraper; polite, 1 req/sec)"}


def get(session: requests.Session, url: str, retries: int = 3) -> requests.Response:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r
        except requests.RequestException as err:
            if attempt == retries:
                raise
            print(f"  retry {attempt} for {url}: {err}")
            time.sleep(2 * attempt)


# ---------- 1. login ----------

def login(session: requests.Session, base: str, user: str, password: str):
    login_url = urljoin(base, "/login")
    soup = BeautifulSoup(get(session, login_url).text, "html.parser")
    token_input = soup.select_one("input[name=csrf_token]")
    if token_input is None:
        sys.exit("Login form not found (no csrf_token field).")
    payload = {"csrf_token": token_input["value"], "username": user, "password": password}
    r = session.post(login_url, data=payload, headers=HEADERS, timeout=15)
    r.raise_for_status()
    if not BeautifulSoup(r.text, "html.parser").select_one('a[href="/logout"]'):
        sys.exit("Login failed: no Logout link after submitting the form.")
    print("Logged in (CSRF token accepted, session cookie stored)")


# ---------- 2. list pages ----------

def scrape_list(session, base: str, max_pages: int | None, delay: float) -> list[dict]:
    url, page, rows = urljoin(base, "/"), 0, []
    while url and (max_pages is None or page < max_pages):
        page += 1
        soup = BeautifulSoup(get(session, url).text, "html.parser")
        quotes = soup.select("div.quote")
        for q in quotes:
            about = q.select_one('a[href^="/author/"]')
            rows.append({
                "Quote": q.select_one("span.text").get_text(strip=True).strip("“”\""),
                "Author": q.select_one("small.author").get_text(strip=True),
                "Tags": ", ".join(t.get_text(strip=True) for t in q.select("div.tags a.tag")),
                # trailing slash: without it the site redirects https -> plain http
                "Author URL": urljoin(base, about["href"].rstrip("/") + "/") if about else "",
                "Page": page,
            })
        print(f"  list page {page}: {len(quotes)} quotes (total {len(rows)})")
        nxt = soup.select_one("li.next > a")
        url = urljoin(url, nxt["href"]) if nxt else None
        if url:
            time.sleep(delay)
    return rows


# ---------- 3. detail pages ----------

def scrape_authors(session, urls: list[str], delay: float) -> list[dict]:
    authors = []
    for i, url in enumerate(urls, 1):
        soup = BeautifulSoup(get(session, url).text, "html.parser")
        desc = soup.select_one("div.author-description").get_text(" ", strip=True)
        authors.append({
            "Author": soup.select_one("h3.author-title").get_text(strip=True),
            "Born": soup.select_one("span.author-born-date").get_text(strip=True),
            "Birthplace": soup.select_one("span.author-born-location").get_text(strip=True).removeprefix("in ").strip(),
            "Bio (first 200 chars)": desc[:200] + ("…" if len(desc) > 200 else ""),
            "Author URL": url,
        })
        if i % 10 == 0 or i == len(urls):
            print(f"  author pages: {i}/{len(urls)}")
        time.sleep(delay)
    return authors


# ---------- 4. report ----------

def style(ws, wrap=False):
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor="1F6F43")
        c.font = Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row), start=1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 3, 10), 60)
    if wrap:
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")


def save_excel(quotes: list[dict], authors: list[dict], out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    q = pd.DataFrame(quotes)
    a = pd.DataFrame(authors)
    counts = q.groupby("Author").size().rename("Quotes").reset_index()
    a = a.merge(counts, on="Author", how="left").sort_values(["Quotes", "Author"], ascending=[False, True])
    a = a[["Author", "Quotes", "Born", "Birthplace", "Bio (first 200 chars)", "Author URL"]]
    q = q.merge(a[["Author", "Born", "Birthplace"]], on="Author", how="left")
    q = q[["Quote", "Author", "Born", "Birthplace", "Tags", "Page"]]
    summary = pd.DataFrame({
        "Metric": ["List pages scraped", "Quotes collected", "Author detail pages visited",
                   "Authors with birth date", "Quotes linked to author details"],
        "Value": [q["Page"].max(), len(q), len(a), int(a["Born"].astype(bool).sum()),
                  int(q["Born"].notna().sum())],
    })
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        q.to_excel(xw, sheet_name="Quotes", index=False)
        a.to_excel(xw, sheet_name="Authors", index=False)
        summary.to_excel(xw, sheet_name="Summary", index=False)
        style(xw.sheets["Quotes"], wrap=True)
        style(xw.sheets["Authors"], wrap=True)
        style(xw.sheets["Summary"])
    return q, a


def main():
    ap = argparse.ArgumentParser(description="Log in, scrape list + detail pages into Excel.")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--user", default=os.environ.get("SCRAPER_USER"))
    ap.add_argument("--password", default=os.environ.get("SCRAPER_PASS"))
    ap.add_argument("--pages", type=int, default=None, help="limit list pages (default: all)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--output", type=Path, default=Path(__file__).parent / "output" / "quotes_authors.xlsx")
    args = ap.parse_args()
    if not args.user or not args.password:
        sys.exit("Set credentials: --user/--password or SCRAPER_USER/SCRAPER_PASS env vars.")

    start = time.time()
    session = requests.Session()
    login(session, args.base, args.user, args.password)
    quotes = scrape_list(session, args.base, args.pages, args.delay)
    author_urls = sorted({r["Author URL"] for r in quotes if r["Author URL"]})
    print(f"Visiting {len(author_urls)} author detail pages ...")
    authors = scrape_authors(session, author_urls, args.delay)
    q, a = save_excel(quotes, authors, args.output)
    print(f"Done: {len(q)} quotes, {len(a)} authors linked, saved to output/{args.output.name} "
          f"in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
