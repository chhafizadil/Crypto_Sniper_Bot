# main.py
# Simplified Telegram Bot script for Koyeb deployment without FastAPI
# Uses python-telegram-bot for webhook and aiohttp for health check
# Enhanced /health endpoint to handle various response formats and detailed logging
# Retained batch scanning, cooldown, volume checks, and ML predictions
# Optimized memory usage for Koyeb free tier (512MB RAM)
# Limited to 10 high-volume USDT pairs

import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import TelegramError
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
from aiohttp import web

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '-4694205383')
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
WEBHOOK_URL = 'https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook'
MIN_VOLUME = 2_000_000  # 2 million USD
MAX_SIGNALS_PER_MINUTE = 1
CYCLE_INTERVAL = 600  # 10 minutes to reduce load
BATCH_SIZE = 5  # Reduced for memory
COOLDOWN = 6 * 3600  # 6 hours
SIGNAL_TIME_FILE = 'logs/last_signal_times.json'

# Track scanned symbols and signal times
scanned_symbols: Set[str] = set()
last_signal_time: Dict[str, datetime] = {}

def load_signal_times():
    # Load last signal times from JSON file
    try:
        if os.path.exists(SIGNAL_TIME_FILE):
            with open(SIGNAL_TIME_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading signal times: {str(e)}")
        return {}

def save_signal_times():
    # Save last signal times to JSON file
    try:
        with open(SIGNAL_TIME_FILE, 'w') as f:
            json.dump({k: v.isoformat() for k, v in last_signal_time.items()}, f)
    except Exception as e:
        logger.error(f"Error saving signal times: {str(e)}")

def format_timestamp_to_pk(utc_timestamp_str):
    # Convert UTC timestamp to Pakistan time
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone('Asia/Karachi'))
        return pk_time.strftime('%d %B %Y, %I:%M %p')
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

def determine_leverage(indicators):
    # Determine leverage based on indicator signals
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(', ')
    if 'MACD' in indicators:
        score += 2
    if 'Strong Trend' in indicators:
        score += 2
    if 'VWAP' in indicators:
        score += 1
    if 'Stochastic' in indicators:
        score -= 1
    return '40x' if score >= 5 else '30x' if score >= 3 else '20x' if score >= 1 else '10x'

def get_24h_volume(symbol):
    # Fetch 24-hour trading volume from Binance
    try:
        symbol_clean = symbol.replace('/', '').upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}"
        response = requests.get(url, timeout=5)
        data = response.json()
        quote_volume = float(data.get('quoteVolume', 0))
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching volume for {symbol}: {str(e)}")
        return 0, '$0.00'

async def fetch_usdt_pairs(exchange):
    # Fetch high-volume USDT trading pairs from Binance
    try:
        markets = await exchange.load_markets()
        symbols = [symbol for symbol in markets if symbol.endswith('USDT')]
        symbols = [s for s in symbols if get_24h_volume(s)[0] > 10_000_000][:10]  # Limit to top 10
        logger.info(f"Found {len(symbols)} USDT pairs")
        return symbols
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        return []

# Telegram command handlers
async def start(update, context):
    # Handle /start command
    try:
        await update.message.reply_text('Crypto Signal Bot is running! Use /summary, /report, /status, /signal, or /help.')
        logger.info('Start command executed')
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")

async def help(update, context):
    # Handle /help command
    try:
        help_text = (
            '📚 Crypto Signal Bot Commands\n'
            '/start - Start bot\n'
            '/summary - Today\'s signal summary\n'
            '/report - Detailed daily trading report\n'
            '/status - Bot status\n'
            '/signal - Latest signal\n'
            '/test - Test bot connectivity\n'
            '/help - This help message'
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        logger.info('Help command executed')
    except Exception as e:
        logger.error(f"Error in help command: {str(e)}")

async def test(update, context):
    # Handle /test command
    try:
        await update.message.reply_text('Test message from Crypto Signal Bot!')
        logger.info('Test message sent successfully')
    except Exception as e:
        logger.error(f"Error sending test message: {str(e)}")
        await update.message.reply_text(f"Error sending test message: {str(e)}")

async def status(update, context):
    # Handle /status command
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
        logger.info('Status command executed')
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        await update.message.reply_text('🔴 Bot status check failed.', parse_mode='Markdown')

async def signal(update, context):
    # Handle /signal command
    try:
        file_path = 'logs/signals_log.csv'
        if not os.path.exists(file_path):
            await update.message.reply_text('No signals available.')
            return
        df = pd.read_csv(file_path)
        if df.empty:
            await update.message.reply_text('No signals available.')
            return
        latest_signal = df.iloc[-1].to_dict()
        conditions_str = ', '.join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) and latest_signal['conditions'].startswith('[') else latest_signal['conditions'].split(', '))

        volume, volume_str = get_24h_volume(latest_signal['symbol'])
        if volume < MIN_VOLUME:
            logger.warning(f"Low signal volume for {latest_signal['symbol']}: {volume_str}")
            await update.message.reply_text('Insufficient signal volume.')
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
        logger.info('Signal command executed')
    except Exception as e:
        logger.error(f"Error fetching latest signal: {str(e)}")
        await update.message.reply_text('Error fetching latest signal.')

async def summary(update, context):
    # Handle /summary command
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text('No signals for today.')
        logger.info('Summary command executed')
    except Exception as e:
        logger.error(f"Error in summary command: {str(e)}")

async def report(update, context):
    # Handle /report command
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text('No detailed report for today.')
        logger.info('Report command executed')
    except Exception as e:
        logger.error(f"Error in report command: {str(e)}")

async def process_signal(symbol, exchange):
    # Process trading signal for a symbol
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
        ohlcv = await fetch_realtime_data(symbol, '15m', limit=50)  # Reduced for memory
        if ohlcv is None or len(ohlcv) < 30:
            logger.warning(f"[{symbol}] Insufficient data")
            return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).astype(np.float32)  # Optimize memory
        signal = await predictor.predict_signal(symbol, df, '15m')
        if not signal:
            logger.info(f"No signal generated for {symbol}")
            return None

        signal['quote_volume_24h'] = volume_str
        update_signal_log(symbol, signal, 'pending')
        await send_signal(symbol, signal, CHAT_ID)
        logger.info(f"Signal generated for {symbol}")
        return signal
    except Exception as e:
        logger.error(f"Error processing signal for {symbol}: {str(e)}")
        return None

async def handle_health(request):
    # Handle /health endpoint for Koyeb health check with multiple response formats
    logger.info(f"Health check requested: path={request.path}, headers={dict(request.headers)}")
    # Return simple 200 OK with text for compatibility
    return web.Response(status=200, text='OK')

async def handle_webhook(request):
    # Handle Telegram webhook updates
    try:
        data = await request.json()
        logger.info(f"Received webhook update: {data}")
        update = telegram.Update.de_json(data, bot=telegram.Bot(token=BOT_TOKEN))
        if update:
            await application.process_update(update)
            logger.info('Webhook update processed')
        else:
            logger.error('Invalid webhook update')
        return web.json_response({'status': 'ok'}, status=200)
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return web.json_response({'error': str(e)}, status=400)

async def start_bot():
    # Start aiohttp server, Telegram bot, and signal scanning loop
    global last_signal_time, application
    os.makedirs('logs', exist_ok=True)  # Ensure logs directory exists
    try:
        # Set up aiohttp server first
        app = web.Application()
        app.add_routes([web.get('/health', handle_health)])
        app.add_routes([web.get('/', handle_health)])  # Fallback for root path
        app.add_routes([web.post('/webhook', handle_webhook)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8000)
        await site.start()
        logger.info('aiohttp server started on port 8000')

        # Initialize Telegram bot
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info('Telegram webhook removed')
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set: {WEBHOOK_URL}")
        await bot.send_message(chat_id=CHAT_ID, text='Bot started successfully!')

        # Initialize Telegram application
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('summary', summary))
        application.add_handler(CommandHandler('report', report))
        application.add_handler(CommandHandler('status', status))
        application.add_handler(CommandHandler('signal', signal))
        application.add_handler(CommandHandler('test', test))
        application.add_handler(CommandHandler('help', help))
        await application.initialize()
        await application.start()
        logger.info('Telegram webhook bot started')

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })

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
                            logger.info('Max signals per minute reached, skipping')
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
                    logger.info('Completed scan cycle, retaining cooldown symbols')

                await asyncio.sleep(CYCLE_INTERVAL)

            except Exception as e:
                logger.error(f"Scanning loop error: {str(e)}", exc_info=True)
                await asyncio.sleep(60)

        await exchange.close()

    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    # Start bot and server
    asyncio.run(start_bot())
