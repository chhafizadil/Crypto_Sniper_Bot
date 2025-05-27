# Main script for Telegram bot integration with FastAPI for Koyeb deployment
# Aligned with merged files (indicators.py, predictor.py, sender.py, report_generator.py, trainer.py)
# Changes:
# - Added FastAPI for /health and /webhook endpoints to fix Koyeb health check
# - Integrated Telegram bot with FastAPI webhook handling
# - Retained original logic (batch scanning, cooldown, volume checks, ML predictions)
# - Ensured compatibility with gunicorn and uvicorn
# - Fixed import and dependency issues

import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict, NetworkError, TelegramError
from utils.logger import logger
from datetime import datetime, timedelta
import os
import pytz
import requests
from dotenv import load_dotenv
import numpy as np
import json
from model.predictor import SignalPredictor
from telebot.sender import send_signal, update_signal_log
from data.collector import fetch_realtime_data
from core.indicators import calculate_tp_probabilities_and_prices, adjust_tp_for_stablecoin
from telebot.report_generator import generate_daily_summary
import ccxt.async_support as ccxt
from typing import Set, Dict
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

# Initialize FastAPI app for Koyeb
app = FastAPI()

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
WEBHOOK_URL = "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook"
MIN_VOLUME = 2_000_000  # 2 million USD
MAX_SIGNALS_PER_MINUTE = 1
CYCLE_INTERVAL = 1200  # 20 minutes
BATCH_SIZE = 5
COOLDOWN = 6 * 3600  # 6 hours
SIGNAL_TIME_FILE = "last_signal_times.json"

# Track scanned symbols and signal times
scanned_symbols: Set[str] = set()
last_signal_time: Dict[str, datetime] = {}

# Initialize Telegram bot application
telegram_app = None

def load_signal_times():
    # Load last signal times from JSON
    if os.path.exists(SIGNAL_TIME_FILE):
        with open(SIGNAL_TIME_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_signal_times():
    # Save last signal times to JSON
    with open(SIGNAL_TIME_FILE, 'w') as f:
        json.dump({k: v.isoformat() for k, v in last_signal_time.items()}, f)

def format_timestamp_to_pk(utc_timestamp_str):
    # Convert UTC timestamp to Pakistan time
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

def determine_leverage(indicators):
    # Determine leverage based on indicators
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:
        score += 2
    if "Strong Trend" in indicators:
        score += 2
    if "VWAP" in indicators:
        score += 1
    if "Stochastic" in indicators:
        score -= 1
    return "40x" if score >= 5 else "30x" if score >= 3 else "20x" if score >= 1 else "10x"

def get_24h_volume(symbol):
    # Fetch 24-hour volume from Binance
    try:
        symbol_clean = symbol.replace("/", "").upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}"
        response = requests.get(url, timeout=5)
        data = response.json()
        quote_volume = float(data.get("quoteVolume", 0))
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching 24-hour volume for {symbol}: {str(e)}")
        return 0, "$0.00"

async def fetch_usdt_pairs(exchange):
    # Fetch all USDT pairs from Binance
    try:
        markets = await exchange.load_markets()
        symbols = [symbol for symbol in markets if symbol.endswith('USDT')]
        logger.info(f"Found {len(symbols)} USDT pairs")
        return symbols
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        return []

# Telegram command handlers
async def start(update, context):
    await update.message.reply_text("Crypto Signal Bot is running! Use /summary, /report, /status, /signal, or /help.")

async def help(update, context):
    help_text = (
        "📚 Crypto Signal Bot Commands\n"
        "/start - Start bot\n"
        "/summary - Today's signal summary\n"
        "/report - Detailed daily trading report\n"
        "/status - Bot status\n"
        "/signal - Latest signal\n"
        "/test - Bot connectivity test\n"
        "/help - This help message"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def test(update, context):
    try:
        await update.message.reply_text("Test message from Crypto Signal Bot!")
        logger.info("Test message sent successfully")
    except Exception as e:
        logger.error(f"Error sending test message: {str(e)}")
        await update.message.reply_text(f"Error sending test message: {str(e)}")

async def status(update, context):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        bot_info = await bot.get_me()
        webhook_info = await bot.get_webhook_info()
        status_text = (
            f"🟢 Bot is running normally\n"
            f"🤖 Bot: @{bot_info.username}\n"
            f"🌐 Webhook: {webhook_info.url or 'Not set'}\n"
            f"📡 Pending updates: {webhook_info.pending_update_count or 0}"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        await update.message.reply_text("🔴 Bot status check failed.", parse_mode='Markdown')

async def signal(update, context):
    try:
        file_path = 'logs/signals_log.csv'
        if not os.path.exists(file_path):
            await update.message.reply_text("No signals available.")
            return
        df = pd.read_csv(file_path)
        if df.empty:
            await update.message.reply_text("No signals available.")
            return
        latest_signal = df.iloc[-1].to_dict()
        conditions_str = ", ".join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) and latest_signal['conditions'].startswith('[') else latest_signal['conditions'].split(", "))

        volume, volume_str = get_24h_volume(latest_signal['symbol'])
        if volume < MIN_VOLUME:
            logger.warning(f"Low signal volume for {latest_signal['symbol']}: {volume_str}")
            await update.message.reply_text("Insufficient signal volume.")
            return

        latest_signal['leverage'] = determine_leverage(latest_signal['conditions'])
        latest_signal['quote_volume_24h'] = volume_str
        latest_signal['timestamp'] = format_timestamp_to_pk(latest_signal['timestamp'])

        message = (
            f"📈 Trading Signal\n"
            f"💱 Symbol: {latest_signal['symbol']}\n"
            f"📊 Direction: {latest_signal['direction']}\n"
            f"⏰ Timeframe: {latest_signal['timeframe']}\n"
            f"⏳ Duration: {latest_signal['trade_duration']}\n"
            f"💰 Entry: ${latest_signal['entry']:.2f}\n"
            f"🎯 TP1: ${latest_signal['tp1']:.2f} ({latest_signal['tp1_possibility']:.2f}%)\n"
            f"🎯 TP2: ${latest_signal['tp2']:.2f} ({latest_signal['tp2_possibility']:.2f}%)\n"
            f"🎯 TP3: ${latest_signal['tp3']:.2f} ({latest_signal['tp3_possibility']:.2f}%)\n"
            f"🛑 SL: ${latest_signal['sl']:.2f}\n"
            f"🔍 Confidence: {latest_signal['confidence']:.2f}%\n"
            f"⚡ Type: {latest_signal['trade_type']}\n"
            f"⚖ Leverage: {latest_signal.get('leverage', 'N/A')}\n"
            f"📈 Combined Candle Volume: ${latest_signal['volume']:,.2f}\n"
            f"📈 24h Volume: {latest_signal['quote_volume_24h']}\n"
            f"🔎 Indicators: {conditions_str}\n"
            f"🕒 Timestamp: {latest_signal['timestamp']}"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error fetching latest signal: {str(e)}")
        await update.message.reply_text("Error fetching latest signal.")

async def summary(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("No signals for today.")

async def report(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("No detailed report for today.")

async def process_signal(symbol, exchange):
    # Process signal for a symbol
    try:
        current_time = datetime.now(pytz.UTC)
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]).total_seconds() < COOLDOWN:
            logger.info(f"Skipping {symbol}: Signal sent within last 6 hours")
            return None

        volume, volume_str = get_24h_volume(symbol)
        if volume < MIN_VOLUME:
            logger.info(f"Rejecting {symbol}: Low volume ({volume_str} < ${MIN_VOLUME:,})")
            return None

        predictor = SignalPredictor()
        ohlcv = await fetch_realtime_data(symbol, '15m', limit=50)
        if ohlcv is None or len(ohlcv) < 30:
            logger.warning(f"[{symbol}] Insufficient data")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        signal = await predictor.predict_signal(symbol, df, '15m')
        if not signal:
            logger.info(f"No signal generated for {symbol}")
            return None

        signal['quote_volume_24h'] = volume_str
        update_signal_log(symbol, signal, "pending")
        await send_signal(symbol, signal, CHAT_ID)
        return signal
    except Exception as e:
        logger.error(f"Error processing signal for {symbol}: {str(e)}")
        return None

# FastAPI endpoints
@app.get("/health")
async def health_check():
    # Health check for Koyeb
    return JSONResponse(status_code=200, content={"status": "healthy"})

@app.post("/webhook")
async def webhook(request: Request):
    # Handle Telegram webhook updates
    try:
        update = telegram.Update.de_json(await request.json(), telegram_app.bot)
        await telegram_app.process_update(update)
        return JSONResponse(status_code=200, content={"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=400, content={"error": str(e)})

async def start_bot():
    # Start bot and run scanning loop
    os.makedirs(os.path.dirname(SIGNAL_TIME_FILE), exist_ok=True)  # Ensure logs directory exists
    global telegram_app
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram webhook removed")
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set: {WEBHOOK_URL}")
        await bot.send_message(chat_id=CHAT_ID, text="Bot started successfully!")

        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("summary", summary))
        telegram_app.add_handler(CommandHandler("report", report))
        telegram_app.add_handler(CommandHandler("status", status))
        telegram_app.add_handler(CommandHandler("signal", signal))
        telegram_app.add_handler(CommandHandler("test", test))
        telegram_app.add_handler(CommandHandler("help", help))
        await telegram_app.initialize()
        await telegram_app.start()
        logger.info("Telegram webhook bot started")

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })

        global last_signal_time
        last_signal_time = {k: datetime.fromisoformat(v) for k, v in load_signal_times().items()}

        signal_count = 0
        last_signal_minute = (datetime.now(pytz.UTC).timestamp() // 60)

        while True:
            try:
                symbols = await fetch_usdt_pairs(exchange)
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    tasks = [process_signal(symbol, exchange) for symbol in batch if symbol not in scanned_symbols]
                    results = await asyncio.gather(*tasks)
                    scanned_symbols.update(batch)

                    valid_signals = [r for r in results if r is not None]
                    if valid_signals:
                        top_signal = max(valid_signals, key=lambda x: x['confidence'])
                        current_time = datetime.now(pytz.UTC)
                        current_minute = current_time.timestamp() // 60

                        if current_minute > last_signal_minute:
                            signal_count = 0
                            last_signal_minute = current_minute

                        if signal_count >= MAX_SIGNALS_PER_MINUTE:
                            logger.info("Max signals per minute reached, skipping")
                            continue

                        signal_count += 1
                        save_signal_times()

                    await asyncio.sleep(60)

                if len(scanned_symbols) >= len(symbols):
                    current_time = datetime.now(pytz.UTC)
                    scanned_symbols.clear()
                    scanned_symbols.update(
                        s for s in symbols if s in last_signal_time and (current_time - last_signal_time[s]).total_seconds() < COOLDOWN
                    )
                    logger.info("Completed scan cycle, retaining cooldown symbols")

                await asyncio.sleep(CYCLE_INTERVAL)

            except Exception as e:
                logger.error(f"Scanning loop error: {str(e)}")
                await asyncio.sleep(60)

        await exchange.close()

    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
        raise

if __name__ == "__main__":
    import uvicorn
    # Run FastAPI app locally for testing
    uvicorn.run(app, host="0.0.0.0", port=8000)
