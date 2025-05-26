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
from core.engine import process_symbol, fetch_usdt_pairs
import ccxt.async_support as ccxt
from typing import Set, Dict
import http.server
import socketserver
import threading

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8000))
MIN_VOLUME = 2_000_000
MAX_SIGNALS_PER_MINUTE = 1
CYCLE_INTERVAL = 1200
BATCH_SIZE = 20
COOLDOWN = 6 * 3600
SIGNAL_TIME_FILE = "last_signal_times.json"

# Track scanned symbols and last signal times
scanned_symbols: Set[str] = set()
last_signal_time: Dict[str, datetime] = {}
application = None
bot = None

def load_signal_times():
    if os.path.exists(SIGNAL_TIME_FILE):
        with open(SIGNAL_TIME_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_signal_times():
    with open(SIGNAL_TIME_FILE, 'w') as f:
        json.dump({k: v.isoformat() for k, v in last_signal_time.items()}, f)

def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
            return utc_timestamp_str

def calculate_tp_probabilities_and_prices(indicators, entry_price, atr):
    logger.info("Calculating dynamic TP probabilities and prices")
    base_prob = 50
    tp_multipliers = [1.01, 1.015, 1.02]
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:
        base_prob += 10
    if "Strong Trend" in indicators:
        base_prob += 10
    if "Near Support" in indicators or "Near Resistance" in indicators:
        base_prob -= 5
    probabilities = {
        "TP1": min(base_prob, 80),
        "TP2": min(base_prob * 0.7, 60),
        "TP3": min(base_prob * 0.5, 40)
    }
    prices = {
        "TP1": entry_price * (1 + atr * tp_multipliers[0]),
        "TP2": entry_price * (1 + atr * tp_multipliers[1]),
        "TP3": entry_price * (1 + atr * tp_multipliers[2])
    }
    return probabilities, prices

def determine_leverage(indicators):
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

async def get_24h_volume(exchange, symbol):
    try:
        ticker = await exchange.fetch_ticker(symbol)
        quote_volume = float(ticker.get('quoteVolume', 0))
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching 24-hour volume for {symbol}: {str(e)}")
        return 0, "$0.00"

def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

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
        file_path = 'logs/signals.csv'
        if not os.path.exists(file_path):
            await update.message.reply_text("No signals available.")
            return
        df = pd.read_csv(file_path)
        if df.empty:
            await update.message.reply_text("No signals available.")
            return
        latest_signal = df.iloc[-1].to_dict()
        conditions_str = ", ".join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) and latest_signal['conditions'].startswith('[') else latest_signal['conditions'].split(", "))

        volume, volume_str = await get_24h_volume(context.bot_data['exchange'], latest_signal['symbol'])
        if volume < MIN_VOLUME:
            logger.warning(f"Low signal volume for {latest_signal['symbol']}: {volume_str}")
            await update.message.reply_text("Insufficient signal volume.")
            return

        probabilities, prices = calculate_tp_probabilities_and_prices(latest_signal['conditions'], latest_signal['entry'], latest_signal.get('atr', 0.01))
        latest_signal['tp1_possibility'] = probabilities['TP1']
        latest_signal['tp2_possibility'] = probabilities['TP2']
        latest_signal['tp3_possibility'] = probabilities['TP3']
        latest_signal['tp1'] = prices['TP1']
        latest_signal['tp2'] = prices['TP2']
        latest_signal['tp3'] = prices['TP3']
        latest_signal['leverage'] = determine_leverage(latest_signal['conditions'])
        latest_signal['quote_volume_24h'] = volume_str
        latest_signal['timestamp'] = format_timestamp_to_pk(latest_signal['timestamp'])
        latest_signal['tp1'], latest_signal['tp2'], latest_signal['tp3'] = adjust_tp_for_stablecoin(
            latest_signal['symbol'], latest_signal['tp1'], latest_signal['tp2'], latest_signal['tp3'], latest_signal['entry']
        )

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

async def generate_daily_summary():
    try:
        file_path = 'logs/signals.csv'
        if not os.path.exists(file_path):
            logger.warning("Signals log file not found")
            return None
        df = pd.read_csv(file_path)
        today = datetime.now(pytz.timezone("Asia/Karachi")).date()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_today = df[df['timestamp'].dt.date == today]
        if df_today.empty:
            logger.info("No signals found for today")
            return None
        total_signals = len(df_today)
        long_signals = len(df_today[df_today['direction'] == 'LONG'])
        short_signals = len(df_today[df_today['direction'] == 'SHORT'])
        successful_signals = len(df_today[df_today['status'] == 'successful'])
        failed_signals = len(df_today[df_today['status'] == 'failed'])
        pending_signals = len(df_today[df_today['status'] == 'pending'])
        successful_percentage = (successful_signals / total_signals * 100) if total_signals > 0 else 0
        avg_confidence = df_today['confidence'].mean() if total_signals > 0 else 0
        top_symbol = df_today['symbol'].mode()[0] if total_signals > 0 else "N/A"
        most_active_timeframe = df_today['timeframe'].mode()[0] if total_signals > 0 else "N/A"
        total_volume = df_today['volume'].sum() if total_signals > 0 else 0
        tp1_hits = len(df_today[df_today.get('tp1_hit', False) == True]) if 'tp1_hit' in df_today else 0
        tp2_hits = len(df_today[df_today.get('tp2_hit', False) == True]) if 'tp2_hit' in df_today else 0
        tp3_hits = len(df_today[df_today.get('tp3_hit', False) == True]) if 'tp3_hit' in df_today else 0
        sl_hits = len(df_today[df_today.get('sl_hit', False) == True]) if 'sl_hit' in df_today else 0
        report = (
            f"📊 Daily Trading Summary ({today})\n"
            f"📈 Total signals: {total_signals}\n"
            f"🚀 Long signals: {long_signals}\n"
            f"📉 Short signals: {short_signals}\n"
            f"🎯 Successful signals: {successful_signals} ({successful_percentage:.2f}%)\n"
            f"🔍 Average confidence: {avg_confidence:.2f}%\n"
            f"🏆 Top symbol: {top_symbol}\n"
            f"📊 Most active timeframe: {most_active_timeframe}\n"
            f"⚡ Total analyzed volume: {total_volume:,.0f} (USDT)\n"
            f"🔎 Signal status breakdown:\n"
            f"   - TP1 hit: {tp1_hits}\n"
            f"   - TP2 hit: {tp2_hits}\n"
            f"   - TP3 hit: {tp3_hits}\n"
            f"   - SL hit: {sl_hits}\n"
            f"   - Pending: {pending_signals}\n"
            f"Generated: {datetime.now(pytz.timezone('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        logger.info("Daily report generated successfully")
        return report
    except Exception as e:
        logger.error(f"Error generating daily report: {str(e)}")
        return None

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

async def send_signal(signal):
    max_retries = 5
    retry_delay = 10
    for attempt in range(max_retries):
        try:
            conditions_str = ", ".join(signal.get('conditions', [])) or "None"
            volume, volume_str = await get_24h_volume(context.bot_data['exchange'], signal['symbol'])
            if volume < MIN_VOLUME:
                logger.warning(f"Low volume for {signal['symbol']}: {volume_str}")
                return

            probabilities, prices = calculate_tp_probabilities_and_prices(signal.get('conditions', []), signal['entry'], signal.get('atr', 0.01))
            signal['tp1_possibility'] = probabilities['TP1']
            signal['tp2_possibility'] = probabilities['TP2']
            signal['tp3_possibility'] = probabilities['TP3']
            signal['tp1'] = prices['TP1']
            signal['tp2'] = prices['TP2']
            signal['tp3'] = prices['TP3']
            signal['leverage'] = determine_leverage(signal.get('conditions', []))
            signal['quote_volume_24h'] = volume_str
            signal['timestamp'] = format_timestamp_to_pk(signal['timestamp'])
            signal['tp1'], signal['tp2'], signal['tp3'] = adjust_tp_for_stablecoin(
                signal['symbol'], signal['tp1'], signal['tp2'], signal['tp3'], signal['entry']
            )

            message = (
                f"📈 Trading Signal\n"
                f"💱 Symbol: {signal['symbol']}\n"
                f"📊 Direction: {signal['direction']}\n"
                f"⏰ Timeframe: {signal['timeframe']}\n"
                f"⏳ Duration: {signal['trade_duration']}\n"
                f"💰 Entry: ${signal['entry']:.2f}\n"
                f"🎯 TP1: ${signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)\n"
                f"🎯 TP2: ${signal['tp2']:.2f} ({signal['tp2_possibility']:.2f}%)\n"
                f"🎯 TP3: ${signal['tp3']:.2f} ({signal['tp3_possibility']:.2f}%)\n"
                f"🛑 SL: ${signal['sl']:.2f}\n"
                f"🔍 Confidence: {signal['confidence']:.2f}%\n"
                f"⚡ Type: {signal['trade_type']}\n"
                f"⚖ Leverage: {signal.get('leverage', 'N/A')}\n"
                f"📈 Combined Candle Volume: ${signal['volume']:,.2f}\n"
                f"📈 24h Volume: {signal['quote_volume_24h']}\n"
                f"🔎 Indicators: {conditions_str}\n"
                f"🕒 Timestamp: {signal['timestamp']}"
            )
            logger.info(f"Attempting to send signal for {signal['symbol']} (attempt {attempt+1}/{max_retries})")
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
            logger.info(f"Signal sent successfully: {signal['symbol']} - {signal['direction']} ✔")
            last_signal_time[signal['symbol']] = datetime.now(pytz.UTC)
            await asyncio.sleep(3)
            return
        except NetworkError as ne:
            logger.error(f"Network error for {signal['symbol']}: {str(ne)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        except TelegramError as te:
            logger.error(f"Telegram error for {signal['symbol']}: {str(te)}")
            return
        except Exception as e:
            logger.error(f"Failed to send signal for {signal['symbol']}: {str(e)}")
            return
    logger.error(f"Signal failed for {signal['symbol']} after {max_retries} attempts")

async def process_signal(symbol, exchange):
    try:
        current_time = datetime.now(pytz.UTC)
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]).total_seconds() < COOLDOWN:
            logger.info(f"Skipping {symbol}: Signal sent within last 6 hours")
            return None

        volume, volume_str = await get_24h_volume(exchange, symbol)
        if volume < MIN_VOLUME:
            logger.info(f"Rejecting {symbol}: Low volume ({volume_str} < ${MIN_VOLUME:,})")
            return None

        signal_data = await process_symbol(exchange, symbol)
        if not signal_data:
            logger.info(f"No signal generated for {symbol}")
            return None

        signal = signal_data['signal']
        signal['quote_volume_24h'] = volume_str

        df = pd.DataFrame([signal])
        file_path = 'logs/signals.csv'
        if os.path.exists(file_path):
            df.to_csv(file_path, mode='a', header=False, index=False)
        else:
            df.to_csv(file_path, index=False)

        await send_signal(signal)
        return signal
    except Exception as e:
        logger.error(f"Error processing signal for {symbol}: {str(e)}")
        return None

async def start_bot():
    global bot, application
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Telegram webhook successfully removed")
        except Exception as e:
            logger.warning(f"Error removing webhook: {str(e)}")

        try:
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook set: {WEBHOOK_URL}")
        except Conflict:
            logger.warning("Webhook conflict, resetting")
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook reset: {WEBHOOK_URL}")

        try:
            await bot.send_message(chat_id=CHAT_ID, text="Bot started successfully!")
            logger.info("Test message sent to Telegram")
        except Exception as e:
            logger.error(f"Failed to send test message: {str(e)}")

        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("summary", summary))
        application.add_handler(CommandHandler("report", report))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("signal", signal))
        application.add_handler(CommandHandler("test", test))
        application.add_handler(CommandHandler("help", help))
        await application.initialize()
        await application.start()

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        application.bot_data['exchange'] = exchange

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

class WebhookHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode('utf-8'))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                update = json.loads(post_data)
                asyncio.run_coroutine_threadsafe(
                    application.process_update(telegram.Update.de_json(update, bot)),
                    asyncio.get_event_loop()
                )
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                logger.error(f"Webhook error: {str(e)}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    try:
        server = socketserver.TCPServer(('', PORT), WebhookHandler)
        logger.info(f"HTTP server running on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"HTTP server error: {str(e)}")

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_http_server)
    server_thread.start()
    asyncio.run(start_bot())
