# Login + Multi-Page Scraper

Logs into a website (handling the hidden CSRF token in the login form), walks
through every list page, then opens each linked detail page to collect extra
fields, and joins everything into one Excel workbook.

Target: https://quotes.toscrape.com (a public practice site; it accepts any
username and password, so no real account is needed)

**Output (`output/quotes_authors.xlsx`):**
- **Quotes** – every quote with author, birth date, birthplace and tags
- **Authors** – one row per author: quote count, born, birthplace, short bio, URL
- **Summary** – pages, quotes and detail pages collected

Credentials are never stored in the code; they come from arguments or
environment variables.

## Run
```
pip install -r requirements.txt
export SCRAPER_USER=demo
export SCRAPER_PASS=demo
python scraper_login.py --pages 2   # quick test
python scraper_login.py             # all pages (~3 minutes, 1 request/sec)
```
