# Telegram price-alert bot

A Telegram bot that watches crypto prices and messages you when a coin moves
more than the percentage you choose.

## What it does

| Command | Reply |
|---|---|
| `/price btc` | Current price and 24h change |
| `/top` | Top 5 coins by market cap |
| `/watch btc 2` | Alert me when BTC moves ±2% from now |
| `/unwatch btc` | Stop watching BTC |
| `/list` | Everything I'm watching |

- Checks prices every 5 minutes (change with `--interval`)
- One alert per move: after an alert, the new price becomes the reference
- Watches and alert history are saved in SQLite (`output/bot.db`), so they survive restarts
- Handles typos, unknown coins, bad thresholds, network errors and API rate limits
- The bot token is read from an environment variable, never stored in the code

## Setup

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name, and copy the token.
2. Install and run:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=123456:ABC...
python bot.py                 # or: python bot.py --interval 60
```

3. Open your bot in Telegram and send `/start`.

To keep it running 24/7, run it on a small cloud server (or any always-on PC)
with `nohup python bot.py &`, `systemd`, or `screen`.

## Built with

Python, requests, SQLite, Telegram Bot API, CoinGecko public API.
The same structure works for any alert: product prices, stock levels, new
listings on a website, or form submissions.
