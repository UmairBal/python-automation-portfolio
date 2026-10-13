# JavaScript-Rendered Site Scraper (Playwright)

Many modern websites load their content with JavaScript, so a normal HTTP request
returns an empty page. This scraper drives a real headless browser, waits for the
content to render, extracts it and follows pagination.

Target: https://quotes.toscrape.com/js/ (a public site made for scraping practice)

**Output (`output/quotes_data.xlsx`):**
- **Quotes** – text, author, tags and page for every quote
- **By Author** – number of quotes per author
- **By Tag** – how often each tag appears

## Run
```
pip install -r requirements.txt
playwright install chromium     # not needed if Google Chrome is installed
python scraper_js.py --pages 2   # quick test
python scraper_js.py             # all pages
python scraper_js.py --headed    # watch the browser work
```
