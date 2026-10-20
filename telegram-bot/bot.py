"""
Telegram price-alert bot.

Chat commands:
    /start, /help          show the commands
    /price btc             current price and 24h change
    /top                   top 5 coins by market cap
    /watch btc 2           alert me when BTC moves 2% (up or down) from now
    /unwatch btc           stop watching a coin
    /list                  show what I'm watching

Every few minutes the bot checks prices and sends an alert to each chat whose
watched coin moved more than its threshold. After an alert, the new price
becomes the reference, so you get one message per move, not a flood.

Data source: CoinGecko public API (no key needed). Watches and alerts are
stored in a local SQLite file, so they survive restarts.

The bot token is never written in the code:
    export TELEGRAM_BOT_TOKEN=123456:ABC...
    python bot.py
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
TELEGRAM_API = "https://api.telegram.org"
PRICE_API = "https://api.coingecko.com/api/v3/coins/markets"
HEADERS = {"User-Agent": "telegram-price-bot-portfolio/1.0", "Accept": "application/json"}

HELP = (
    "I watch crypto prices and message you when they move.\n\n"
    "/price btc - current price\n"
    "/top - top 5 coins\n"
    "/watch btc 2 - alert when BTC moves 2%\n"
    "/unwatch btc - stop watching\n"
    "/list - your watches"
)


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------- Telegram ----------

class Telegram:
    def __init__(self, token: str, base: str = TELEGRAM_API):
        self.url = f"{base}/bot{token}"
        self.offset = 0

    def call(self, method: str, timeout: float = 15, **params):
        r = requests.post(f"{self.url}/{method}", json=params, timeout=timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]

    def updates(self, wait: int) -> list[dict]:
        """Long polling: waits up to `wait` seconds for new messages."""
        r = requests.post(f"{self.url}/getUpdates", json={"offset": self.offset, "timeout": wait},
                          timeout=wait + 10)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data.get('description')}")
        result = data["result"]
        if result:
            self.offset = result[-1]["update_id"] + 1
        return result

    def send(self, chat_id: int, text: str):
        self.call("sendMessage", chat_id=chat_id, text=text)


# ---------- prices ----------

class Prices:
    """Top-100 coins, refreshed at most once a minute to respect the free API."""

    def __init__(self, url: str = PRICE_API):
        self.url, self.cache, self.fetched = url, {}, 0.0

    def refresh(self, force: bool = False) -> dict:
        if not force and time.time() - self.fetched < 60 and self.cache:
            return self.cache
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 100, "page": 1,
                  "price_change_percentage": "24h"}
        for attempt in range(1, 4):
            try:
                r = requests.get(self.url, params=params, headers=HEADERS, timeout=20)
                if r.status_code == 429:
                    raise requests.RequestException("rate limited (429)")
                r.raise_for_status()
                self.cache = {c["symbol"].lower(): {"id": c["id"], "symbol": c["symbol"].upper(),
                                                    "name": c["name"], "price": float(c["current_price"]),
                                                    "change24": c.get("price_change_percentage_24h") or 0.0,
                                                    "rank": c.get("market_cap_rank") or 999}
                              for c in reversed(r.json())}  # reversed: bigger coin wins a symbol clash
                self.fetched = time.time()
                return self.cache
            except (requests.RequestException, ValueError) as err:
                if attempt == 3:
                    log(f"price fetch failed: {err}")
                    return self.cache
                time.sleep(5 * attempt)

    def get(self, symbol: str):
        return self.refresh().get(symbol.lower().lstrip("$"))


def fmt_price(p: float) -> str:
    return f"${p:,.2f}" if p >= 1 else f"${p:.6f}".rstrip("0")


# ---------- storage ----------

def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS watches (
            chat_id INTEGER, symbol TEXT, threshold REAL, base_price REAL, created_at TEXT,
            PRIMARY KEY (chat_id, symbol));
        CREATE TABLE IF NOT EXISTS alerts (
            sent_at TEXT, chat_id INTEGER, symbol TEXT, old_price REAL, new_price REAL, change_pct REAL);
    """)
    return con


# ---------- commands ----------

def handle(cmd: str, args: list[str], chat_id: int, con, prices: Prices) -> str:
    if cmd in ("/start", "/help"):
        return HELP

    if cmd == "/top":
        coins = sorted(prices.refresh().values(), key=lambda c: c["rank"])[:5]
        if not coins:
            return "Prices are unavailable right now, try again in a minute."
        return "Top 5 by market cap:\n" + "\n".join(
            f"{c['rank']}. {c['symbol']}  {fmt_price(c['price'])}  ({c['change24']:+.2f}% 24h)" for c in coins)

    if cmd == "/list":
        rows = con.execute("SELECT symbol, threshold, base_price FROM watches WHERE chat_id=? ORDER BY symbol",
                           (chat_id,)).fetchall()
        if not rows:
            return "You're not watching anything yet. Try /watch btc 2"
        return "Watching:\n" + "\n".join(f"{s.upper()}: alert at ±{t:g}% from {fmt_price(b)}" for s, t, b in rows)

    if cmd in ("/price", "/watch", "/unwatch") and not args:
        return f"Usage: {cmd} btc" + (" 2" if cmd == "/watch" else "")

    if cmd == "/unwatch":
        n = con.execute("DELETE FROM watches WHERE chat_id=? AND symbol=?", (chat_id, args[0].lower())).rowcount
        con.commit()
        return f"Stopped watching {args[0].upper()}." if n else f"You weren't watching {args[0].upper()}."

    coin = prices.get(args[0])
    if coin is None:
        return f"I couldn't find '{args[0]}' in the top 100 coins. Check the symbol, e.g. btc, eth, sol."

    if cmd == "/price":
        return f"{coin['name']} ({coin['symbol']}): {fmt_price(coin['price'])}  ({coin['change24']:+.2f}% in 24h)"

    if cmd == "/watch":
        try:
            threshold = float(args[1]) if len(args) > 1 else 2.0
            if not 0.1 <= threshold <= 50:
                raise ValueError
        except ValueError:
            return "The threshold should be a percentage between 0.1 and 50, e.g. /watch btc 2"
        con.execute("INSERT OR REPLACE INTO watches VALUES (?,?,?,?,?)",
                    (chat_id, coin["symbol"].lower(), threshold, coin["price"], datetime.now().isoformat(" ", "seconds")))
        con.commit()
        return (f"Watching {coin['symbol']} from {fmt_price(coin['price'])}. "
                f"I'll message you if it moves ±{threshold:g}%.")

    return "Unknown command. Send /help to see what I can do."


def check_alerts(con, prices: Prices, tg: Telegram) -> int:
    rows = con.execute("SELECT chat_id, symbol, threshold, base_price FROM watches").fetchall()
    if not rows:
        return 0
    prices.refresh(force=True)
    sent = 0
    for chat_id, symbol, threshold, base in rows:
        coin = prices.get(symbol)
        if coin is None:
            continue
        change = (coin["price"] - base) / base * 100
        if abs(change) >= threshold:
            arrow = "up" if change > 0 else "down"
            text = (f"{coin['symbol']} is {arrow} {abs(change):.2f}%\n"
                    f"{fmt_price(base)} -> {fmt_price(coin['price'])}\n"
                    f"(your alert: ±{threshold:g}%)")
            try:
                tg.send(chat_id, text)
            except (requests.RequestException, RuntimeError) as err:
                log(f"could not alert chat {chat_id}: {err}")
                continue
            now = datetime.now().isoformat(" ", "seconds")
            con.execute("UPDATE watches SET base_price=? WHERE chat_id=? AND symbol=?", (coin["price"], chat_id, symbol))
            con.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?)", (now, chat_id, coin["symbol"], base, coin["price"], round(change, 3)))
            con.commit()
            log(f"alert -> chat {chat_id}: {coin['symbol']} {change:+.2f}%")
            sent += 1
    return sent


# ---------- main loop ----------

def main():
    ap = argparse.ArgumentParser(description="Telegram bot that alerts you when prices move.")
    ap.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN"))
    ap.add_argument("--interval", type=int, default=300, help="seconds between price checks (default 300)")
    ap.add_argument("--db", type=Path, default=HERE / "output" / "bot.db")
    ap.add_argument("--telegram-api", default=TELEGRAM_API, help=argparse.SUPPRESS)  # for local testing
    ap.add_argument("--price-api", default=PRICE_API, help=argparse.SUPPRESS)
    ap.add_argument("--run-for", type=int, default=0, help=argparse.SUPPRESS)        # stop after N seconds (tests)
    args = ap.parse_args()
    if not args.token:
        sys.exit("Set your bot token: export TELEGRAM_BOT_TOKEN=... (get one from @BotFather)")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con, prices, tg = connect(args.db), Prices(args.price_api), Telegram(args.token, args.telegram_api)
    me = tg.call("getMe")
    log(f"Bot @{me['username']} is running. Price check every {args.interval}s. Ctrl+C to stop.")

    start, next_check = time.time(), time.time() + args.interval
    try:
        while not args.run_for or time.time() - start < args.run_for:
            wait = max(1, min(25, int(next_check - time.time())))
            try:
                updates = tg.updates(wait)
            except (requests.RequestException, RuntimeError) as err:
                log(f"connection problem: {err}; retrying in 5s")
                time.sleep(5)
                updates = []
            for u in updates:
                msg = u.get("message") or {}
                text, chat = (msg.get("text") or "").strip(), msg.get("chat", {}).get("id")
                if not text.startswith("/") or chat is None:
                    continue
                parts = text.split()
                cmd = parts[0].split("@")[0].lower()
                log(f"chat {chat}: {text}")
                try:
                    tg.send(chat, handle(cmd, parts[1:], chat, con, prices))
                except (requests.RequestException, RuntimeError) as err:
                    log(f"could not reply: {err}")
            if time.time() >= next_check:
                n = check_alerts(con, prices, tg)
                watches = con.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
                log(f"price check: {watches} watches, {n} alerts sent")
                next_check = time.time() + args.interval
    except KeyboardInterrupt:
        pass
    log("Bot stopped.")


if __name__ == "__main__":
    main()
