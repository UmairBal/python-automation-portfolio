# Telegram storefront bot with stock control

A shop inside Telegram. Customers browse with buttons, order and get payment
instructions; the owner receives every order with items, total and shipping
details, and stock is tracked automatically. The sample catalog is a fictional
phone-accessories shop (Volt Accessories).

## Customer side

- Browse **categories → products** with buttons (sold-out items are marked)
- **Add to cart** is blocked if there isn't enough stock: *"Sorry, only 3 in stock. You can add 2 more."*
- Cart with subtotal, shipping (free over $50) and remove buttons
- Checkout: name → shipping address → payment method (PayPal, bank transfer, crypto: all editable)
- Gets an **order number + payment instructions**, and an **"I've paid"** button
- Notified when payment is confirmed and when the order ships (with tracking)
- **My orders** shows the status of recent orders

## Owner side

| Command | What it does |
|---|---|
| (automatic) | Every new order arrives in your chat: items, total, name, address, payment method |
| `/paid 1001` | Confirm payment: stock is deducted and the customer is notified |
| `/ship 1001 TRACKING` | Mark shipped; customer gets the tracking number |
| `/cancel 1001` | Cancel and put the stock back |
| `/orders` | All open orders |
| `/stock` | Low-stock and sold-out list + `output/restock_report.csv` for supplier orders |
| `/sync` | Reload products, prices and stock from the Google Sheet |

**No overselling:** stock is reserved the moment an order is placed, so two
customers can't buy the last unit. Unpaid orders expire after 24 hours and
release their stock.

## Setup

1. Create a bot with **@BotFather** and copy the token.
2. Put your products in a Google Sheet with columns
   `sku, category, name, variant, price, stock`, then
   *File → Share → Publish to web → CSV* and copy the link (or use `catalog.csv`).
3. Run:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export CATALOG="https://docs.google.com/spreadsheets/d/e/.../pub?output=csv"
python store_bot.py
```

4. Send `/myid` to your bot, then restart with `export OWNER_CHAT_ID=<that number>`.

Edit `SHOP`, `SHIPPING`, `FREE_SHIPPING_FROM` and `PAYMENT_METHODS` at the top of
`store_bot.py` for your own shop.

## Built with

Python, requests, SQLite, Telegram Bot API (inline keyboards), Google Sheets CSV.
