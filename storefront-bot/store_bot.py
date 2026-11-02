"""
Telegram storefront bot: customers browse, order and pay; you get every order.

Customers (buttons, no typing needed):
    browse categories -> products -> add to cart (blocked if not enough stock)
    checkout -> name, shipping address, payment method -> order number + payment instructions
    "I've paid" button -> you are notified to confirm

You (the owner chat):
    every new order arrives with items, total, shipping details and payment method
    /paid 1001        confirm payment: stock is deducted, customer is notified
    /ship 1001 TRACK  mark as shipped (tracking number optional), customer is notified
    /cancel 1001      cancel an order and release its stock
    /orders           open orders
    /stock            low-stock report (+ output/restock_report.csv for your next supplier order)
    /sync             reload products, prices and stock from the Google Sheet

Stock is reserved as soon as an order is placed, so two customers can never
buy the last item twice. Unpaid orders expire (default 24 h) and release stock.

The catalog lives in a Google Sheet (File -> Share -> Publish to web -> CSV)
or a local catalog.csv with columns: sku, category, name, variant, price, stock

    export TELEGRAM_BOT_TOKEN=...      (from @BotFather)
    export OWNER_CHAT_ID=...           (send /myid to the bot to find yours)
    export CATALOG=https://docs.google.com/.../pub?output=csv   (or catalog.csv)
    python store_bot.py
"""

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).parent
SHOP = "Volt Accessories"
SHIPPING = 5.00                 # flat shipping fee
FREE_SHIPPING_FROM = 50.00
LOW_STOCK = 5
PAYMENT_METHODS = {             # edit to your own payment details
    "paypal": ("PayPal", "Send {total} to pay@voltaccessories.example (Friends & Family off). "
                         "Put order #{id} in the note."),
    "bank": ("Bank transfer", "Transfer {total} to Volt Accessories Ltd, IBAN XX00 0000 0000 0000, "
                              "reference #{id}."),
    "crypto": ("USDT (TRC20)", "Send {total} USDT to TXexampleWalletAddress000000000. "
                               "Reply with the transaction ID."),
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def money(x):
    return f"${x:,.2f}"


# ---------- Telegram ----------

class TG:
    def __init__(self, token, base="https://api.telegram.org"):
        self.url, self.offset = f"{base}/bot{token}", 0

    def call(self, method, **params):
        r = requests.post(f"{self.url}/{method}", json=params, timeout=40)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"{method}: {data.get('description')}")
        return data["result"]

    def updates(self, wait=25):
        res = self.call("getUpdates", offset=self.offset, timeout=wait, allowed_updates=["message", "callback_query"])
        if res:
            self.offset = res[-1]["update_id"] + 1
        return res

    def send(self, chat, text, buttons=None):
        p = {"chat_id": chat, "text": text}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **p)

    def edit(self, chat, msg_id, text, buttons=None):
        p = {"chat_id": chat, "message_id": msg_id, "text": text,
             "reply_markup": {"inline_keyboard": buttons or []}}
        try:
            return self.call("editMessageText", **p)
        except RuntimeError:                 # message too old or unchanged: send a new one
            return self.send(chat, text, buttons)


def btn(text, data):
    return {"text": text, "callback_data": data}


# ---------- database ----------

def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, category TEXT, name TEXT, variant TEXT,
                                         price REAL, stock INTEGER);
    CREATE TABLE IF NOT EXISTS carts (chat INTEGER, sku TEXT, qty INTEGER, PRIMARY KEY (chat, sku));
    CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, chat INTEGER, user TEXT, items TEXT,
        subtotal REAL, shipping REAL, total REAL, name TEXT, address TEXT, method TEXT,
        status TEXT, tracking TEXT, created TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS sessions (chat INTEGER PRIMARY KEY, step TEXT, data TEXT);
    INSERT OR IGNORE INTO sqlite_sequence (name, seq) SELECT 'orders', 1000
        WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='orders');
    """)
    return con


def load_catalog(con, source):
    if source.startswith("http"):
        text = requests.get(source, timeout=30).text
    else:
        text = Path(source).read_text(encoding="utf-8")
    rows, bad = [], 0
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append((r["sku"].strip(), r["category"].strip(), r["name"].strip(), r.get("variant", "").strip(),
                         float(str(r["price"]).replace("$", "").replace(",", "")), int(float(r["stock"] or 0))))
        except (KeyError, ValueError):
            bad += 1
    with con:
        con.execute("DELETE FROM products")
        con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", rows)
    return len(rows), bad


def reserved(con, sku):
    """Units held by orders that are placed but not yet paid."""
    n = 0
    for (items,) in con.execute("SELECT items FROM orders WHERE status='awaiting payment'"):
        n += sum(i["qty"] for i in json.loads(items) if i["sku"] == sku)
    return n


def available(con, sku):
    row = con.execute("SELECT stock FROM products WHERE sku=?", (sku,)).fetchone()
    return 0 if row is None else max(row["stock"] - reserved(con, sku), 0)


def cart(con, chat):
    return con.execute("""SELECT c.sku, c.qty, p.name, p.variant, p.price FROM carts c
                          JOIN products p USING (sku) WHERE c.chat=? ORDER BY p.category, p.name""", (chat,)).fetchall()


def totals(items):
    sub = sum(i["qty"] * i["price"] for i in items)
    ship = 0.0 if sub >= FREE_SHIPPING_FROM or not items else SHIPPING
    return sub, ship, sub + ship


def session(con, chat, step=None, **data):
    if step is None:
        row = con.execute("SELECT step, data FROM sessions WHERE chat=?", (chat,)).fetchone()
        return (row["step"], json.loads(row["data"])) if row else (None, {})
    with con:
        if step == "":
            con.execute("DELETE FROM sessions WHERE chat=?", (chat,))
        else:
            con.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (chat, step, json.dumps(data)))


# ---------- customer screens ----------

def main_menu():
    return [[btn("🛍 Shop", "cats"), btn("🛒 Cart", "cart")], [btn("📦 My orders", "myorders")]]


def show_categories(con):
    cats = [r[0] for r in con.execute("SELECT DISTINCT category FROM products ORDER BY category")]
    return "Choose a category:", [[btn(c, f"cat|{c}")] for c in cats] + [[btn("🛒 Cart", "cart")]]


def show_category(con, cat):
    rows = con.execute("SELECT * FROM products WHERE category=? ORDER BY name, price", (cat,)).fetchall()
    kb = []
    for p in rows:
        a = available(con, p["sku"])
        label = f"{p['name']} {p['variant']} · {money(p['price'])}" + ("" if a else " · sold out")
        kb.append([btn(label, f"prod|{p['sku']}")])
    return f"{cat}:", kb + [[btn("← Categories", "cats"), btn("🛒 Cart", "cart")]]


def show_product(con, sku, note=""):
    p = con.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
    if p is None:
        return "That product is no longer available.", [[btn("← Categories", "cats")]]
    a = available(con, sku)
    stock = "Sold out" if a == 0 else (f"Only {a} left" if a <= LOW_STOCK else "In stock")
    text = f"{p['name']} ({p['variant']})\n{money(p['price'])}  ·  {stock}" + (f"\n\n{note}" if note else "")
    kb = [[btn("➕ Add 1", f"add|{sku}|1"), btn("➕ Add 3", f"add|{sku}|3")]] if a else []
    return text, kb + [[btn(f"← {p['category']}", f"cat|{p['category']}"), btn("🛒 Cart", "cart")]]


def add_to_cart(con, chat, sku, qty):
    in_cart = (con.execute("SELECT qty FROM carts WHERE chat=? AND sku=?", (chat, sku)).fetchone() or [0])[0]
    a = available(con, sku)
    if a == 0:
        return "Sorry, this item is sold out."
    if in_cart + qty > a:
        can = max(a - in_cart, 0)
        return (f"Sorry, only {a} in stock" + (f" (you have {in_cart} in your cart)." if in_cart else ".")
                + (f" You can add {can} more." if can else ""))
    with con:
        con.execute("INSERT INTO carts VALUES (?,?,?) ON CONFLICT(chat, sku) DO UPDATE SET qty=qty+?",
                    (chat, sku, qty, qty))
    return f"✓ Added {qty}. Cart: {in_cart + qty} of this item."


def show_cart(con, chat):
    items = cart(con, chat)
    if not items:
        return "Your cart is empty.", [[btn("🛍 Shop", "cats")]]
    sub, ship, total = totals(items)
    lines = [f"{i['qty']} × {i['name']} {i['variant']} = {money(i['qty'] * i['price'])}" for i in items]
    text = ("Your cart:\n" + "\n".join(lines) + f"\n\nSubtotal {money(sub)}\nShipping {money(ship)}"
            + (" (free over $50)" if ship == 0 else f" (free over {money(FREE_SHIPPING_FROM)})")
            + f"\nTotal {money(total)}")
    kb = [[btn(f"– 1 {i['name'][:18]} {i['variant'][:10]}", f"dec|{i['sku']}")] for i in items]
    return text, kb + [[btn("✅ Checkout", "checkout"), btn("🗑 Clear", "clear")], [btn("🛍 Keep shopping", "cats")]]


# ---------- orders ----------

def place_order(con, chat, user, name, address, method):
    items = cart(con, chat)
    if not items:
        return None, "Your cart is empty."
    short = [f"{i['name']} {i['variant']} (only {available(con, i['sku'])} left)"
             for i in items if i["qty"] > available(con, i["sku"])]
    if short:                                    # stock changed while they were checking out
        return None, "Sorry, stock changed before you finished:\n" + "\n".join(short) + "\nPlease adjust your cart."
    sub, ship, total = totals(items)
    now = datetime.now().isoformat(" ", "seconds")
    data = [{"sku": i["sku"], "name": f"{i['name']} {i['variant']}", "qty": i["qty"], "price": i["price"]} for i in items]
    with con:
        cur = con.execute("""INSERT INTO orders (chat, user, items, subtotal, shipping, total, name, address,
                             method, status, tracking, created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (chat, user, json.dumps(data), sub, ship, total, name, address, method,
                           "awaiting payment", "", now, now))
        con.execute("DELETE FROM carts WHERE chat=?", (chat,))
    return cur.lastrowid, None


def order_text(o, for_owner=False):
    items = "\n".join(f"  {i['qty']} × {i['name']} @ {money(i['price'])}" for i in json.loads(o["items"]))
    text = (f"Order #{o['id']}  ·  {o['status'].upper()}\n{items}\n"
            f"Subtotal {money(o['subtotal'])} + shipping {money(o['shipping'])} = {money(o['total'])}\n"
            f"Payment: {PAYMENT_METHODS[o['method']][0]}")
    if for_owner:
        text += f"\n\nShip to:\n{o['name']}\n{o['address']}\nCustomer: {o['user']} (chat {o['chat']})"
    if o["tracking"]:
        text += f"\nTracking: {o['tracking']}"
    return text


def get_order(con, ref):
    try:
        return con.execute("SELECT * FROM orders WHERE id=?", (int(str(ref).lstrip("#")),)).fetchone()
    except ValueError:
        return None


def set_status(con, oid, status, tracking=None):
    with con:
        con.execute("UPDATE orders SET status=?, tracking=COALESCE(?, tracking), updated=? WHERE id=?",
                    (status, tracking, datetime.now().isoformat(" ", "seconds"), oid))


def expire_unpaid(con, tg, hours):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(" ", "seconds")
    for o in con.execute("SELECT * FROM orders WHERE status='awaiting payment' AND created < ?", (cutoff,)).fetchall():
        set_status(con, o["id"], "expired")
        tg.send(o["chat"], f"Order #{o['id']} expired because payment wasn't received within {hours:g} h. "
                           f"The items are back in stock. You're welcome to order again.")
        log(f"order #{o['id']} expired")


def stock_report(con):
    rows = con.execute("SELECT * FROM products ORDER BY category, name").fetchall()
    out = HERE / "output" / "restock_report.csv"
    out.parent.mkdir(exist_ok=True)
    low = []
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "category", "product", "stock", "reserved", "available", "status"])
        for p in rows:
            r = reserved(con, p["sku"])
            a = max(p["stock"] - r, 0)
            status = "SOLD OUT" if a == 0 else ("LOW" if a <= LOW_STOCK else "ok")
            w.writerow([p["sku"], p["category"], f"{p['name']} {p['variant']}", p["stock"], r, a, status])
            if status != "ok":
                low.append(f"{'⛔' if a == 0 else '⚠️'} {p['name']} {p['variant']}: {a} available")
    text = (f"Restock needed ({len(low)} of {len(rows)} products):\n" + "\n".join(low)) if low \
        else "All products are above the low-stock level."
    return text + f"\n\nFull report saved to output/{out.name}"


# ---------- update handling ----------

class Store:
    def __init__(self, con, tg, owner, catalog):
        self.con, self.tg, self.owner, self.catalog = con, tg, owner, catalog

    def notify_owner(self, text, buttons=None):
        if self.owner:
            self.tg.send(self.owner, text, buttons)

    # owner commands
    def owner_command(self, cmd, args):
        con = self.con
        if cmd == "/orders":
            rows = con.execute("SELECT * FROM orders WHERE status IN ('awaiting payment','paid') ORDER BY id").fetchall()
            return "\n\n".join(order_text(o, True) for o in rows) or "No open orders."
        if cmd == "/stock":
            return stock_report(con)
        if cmd == "/sync":
            n, bad = load_catalog(con, self.catalog)
            return f"Catalog reloaded: {n} products" + (f" ({bad} rows skipped)" if bad else "") + "."
        if cmd in ("/paid", "/ship", "/cancel"):
            o = get_order(con, args[0]) if args else None
            if o is None:
                return f"Usage: {cmd} 1001" + (" TRACKING" if cmd == "/ship" else "")
            if cmd == "/paid":
                if o["status"] != "awaiting payment":
                    return f"Order #{o['id']} is already {o['status']}."
                with con:                       # reserved units become sold units
                    for i in json.loads(o["items"]):
                        con.execute("UPDATE products SET stock=MAX(stock-?,0) WHERE sku=?", (i["qty"], i["sku"]))
                set_status(con, o["id"], "paid")
                self.tg.send(o["chat"], f"✅ Payment received for order #{o['id']}. We're packing it now!")
                return f"Order #{o['id']} marked paid; stock updated."
            if cmd == "/ship":
                set_status(con, o["id"], "shipped", " ".join(args[1:]) or None)
                o = get_order(con, o["id"])
                self.tg.send(o["chat"], f"📦 Order #{o['id']} has shipped!" +
                             (f"\nTracking: {o['tracking']}" if o["tracking"] else ""))
                return f"Order #{o['id']} marked shipped."
            if cmd == "/cancel":
                if o["status"] == "paid":       # give back stock that was already deducted
                    with con:
                        for i in json.loads(o["items"]):
                            con.execute("UPDATE products SET stock=stock+? WHERE sku=?", (i["qty"], i["sku"]))
                set_status(con, o["id"], "cancelled")
                self.tg.send(o["chat"], f"Order #{o['id']} has been cancelled. Message us if you have questions.")
                return f"Order #{o['id']} cancelled; stock released."
        return None

    def on_message(self, msg):
        chat, text = msg["chat"]["id"], (msg.get("text") or "").strip()
        user = "@" + msg["from"]["username"] if msg.get("from", {}).get("username") else msg.get("from", {}).get("first_name", "customer")
        parts = text.split()
        cmd = parts[0].split("@")[0].lower() if parts else ""
        if cmd == "/myid":
            return self.tg.send(chat, f"Your chat ID is {chat}")
        if chat == self.owner and cmd.startswith("/"):
            reply = self.owner_command(cmd, parts[1:])
            if reply:
                return self.tg.send(chat, reply)
        if cmd in ("/start", "/menu"):
            session(self.con, chat, "")
            return self.tg.send(chat, f"Welcome to {SHOP}! Chargers, cables, cases and more, shipped in 1-2 days.",
                                main_menu())

        step, data = session(self.con, chat)
        if step == "name":
            if len(text) < 3:
                return self.tg.send(chat, "Please send your full name.")
            session(self.con, chat, "address", name=text)
            return self.tg.send(chat, "Thanks! Now send your full shipping address\n(street, city, postcode, country).")
        if step == "address":
            if len(text) < 10:
                return self.tg.send(chat, "That address looks too short. Please include street, city, postcode and country.")
            session(self.con, chat, "method", name=data["name"], address=text)
            kb = [[btn(label, f"pay|{key}")] for key, (label, _) in PAYMENT_METHODS.items()]
            return self.tg.send(chat, "How would you like to pay?", kb)
        return self.tg.send(chat, "Use the buttons below, or send /start.", main_menu())

    def on_button(self, q):
        chat, mid = q["message"]["chat"]["id"], q["message"]["message_id"]
        user = "@" + q["from"]["username"] if q["from"].get("username") else q["from"].get("first_name", "customer")
        action, *args = q["data"].split("|")
        self.tg.call("answerCallbackQuery", callback_query_id=q["id"])
        con, tg = self.con, self.tg

        if action == "cats":
            return tg.edit(chat, mid, *show_categories(con))
        if action == "cat":
            return tg.edit(chat, mid, *show_category(con, args[0]))
        if action == "prod":
            return tg.edit(chat, mid, *show_product(con, args[0]))
        if action == "add":
            note = add_to_cart(con, chat, args[0], int(args[1]))
            return tg.edit(chat, mid, *show_product(con, args[0], note))
        if action == "cart":
            return tg.edit(chat, mid, *show_cart(con, chat))
        if action == "dec":
            with con:
                con.execute("UPDATE carts SET qty=qty-1 WHERE chat=? AND sku=?", (chat, args[0]))
                con.execute("DELETE FROM carts WHERE qty<=0")
            return tg.edit(chat, mid, *show_cart(con, chat))
        if action == "clear":
            with con:
                con.execute("DELETE FROM carts WHERE chat=?", (chat,))
            return tg.edit(chat, mid, *show_cart(con, chat))
        if action == "checkout":
            if not cart(con, chat):
                return tg.edit(chat, mid, *show_cart(con, chat))
            session(con, chat, "name")
            return tg.send(chat, "Checkout 1/3: please send the full name for delivery.")
        if action == "pay":
            step, data = session(con, chat)
            if step != "method":
                return tg.send(chat, "Please start checkout from your cart.", main_menu())
            oid, err = place_order(con, chat, user, data["name"], data["address"], args[0])
            session(con, chat, "")
            if err:
                return tg.send(chat, err, [[btn("🛒 Cart", "cart")]])
            o = get_order(con, oid)
            how = PAYMENT_METHODS[o["method"]][1].format(total=money(o["total"]), id=oid)
            tg.send(chat, order_text(o) + f"\n\nTo pay: {how}\n\nItems are reserved for you for 24 hours.",
                    [[btn("💸 I've paid", f"paid|{oid}")]])
            self.notify_owner("🆕 NEW ORDER\n" + order_text(o, True))
            return log(f"order #{oid} placed by {user}: {money(o['total'])}")
        if action == "paid":
            o = get_order(con, args[0])
            if o and o["chat"] == chat and o["status"] == "awaiting payment":
                tg.send(chat, f"Thanks! We'll check the payment for order #{o['id']} and confirm shortly.")
                self.notify_owner(f"💸 Customer says order #{o['id']} ({money(o['total'])}, "
                                  f"{PAYMENT_METHODS[o['method']][0]}) is paid.\nCheck it, then send /paid {o['id']}")
            return None
        if action == "myorders":
            rows = con.execute("SELECT * FROM orders WHERE chat=? ORDER BY id DESC LIMIT 5", (chat,)).fetchall()
            return tg.edit(chat, mid, "\n\n".join(order_text(o) for o in rows) or "You have no orders yet.",
                           [[btn("🛍 Shop", "cats")]])


def main():
    ap = argparse.ArgumentParser(description="Telegram storefront bot with stock control.")
    ap.add_argument("--catalog", default=os.environ.get("CATALOG", str(HERE / "catalog.csv")))
    ap.add_argument("--db", type=Path, default=HERE / "output" / "store.db")
    ap.add_argument("--expire-hours", type=float, default=24)
    ap.add_argument("--telegram-api", default="https://api.telegram.org", help=argparse.SUPPRESS)
    ap.add_argument("--run-for", type=int, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or sys.exit("Set TELEGRAM_BOT_TOKEN (from @BotFather).")
    owner = int(os.environ["OWNER_CHAT_ID"]) if os.environ.get("OWNER_CHAT_ID") else None
    args.db.parent.mkdir(parents=True, exist_ok=True)
    con, tg = connect(args.db), TG(token, args.telegram_api)
    n, bad = load_catalog(con, args.catalog)
    store = Store(con, tg, owner, args.catalog)
    log(f"@{tg.call('getMe')['username']} is open: {n} products" + (f", {bad} rows skipped" if bad else "")
        + ("" if owner else ". Warning: OWNER_CHAT_ID not set, orders won't be forwarded"))

    start, last_expiry = time.time(), 0
    while not args.run_for or time.time() - start < args.run_for:
        try:
            for u in tg.updates(wait=2 if args.run_for else 25):
                try:
                    if "callback_query" in u:
                        store.on_button(u["callback_query"])
                    elif "message" in u:
                        store.on_message(u["message"])
                except Exception as err:          # one bad update must never stop the shop
                    log(f"error handling update {u.get('update_id')}: {err!r}")
        except (requests.RequestException, RuntimeError) as err:
            log(f"connection problem: {err}; retrying in 5s")
            time.sleep(5)
        except KeyboardInterrupt:
            break
        if time.time() - last_expiry > 600:
            expire_unpaid(con, tg, args.expire_hours)
            last_expiry = time.time()
    log("Store bot stopped.")


if __name__ == "__main__":
    main()
