# main.py
# Main script for Crypto Signal Bot with Telegram integration
# Changes:
# - Enhanced logging for live scan details (Koyeb-like)
# - Dynamic PORT for Cloud Run
# - Integrated engine.py logic
# - Optimized for 512MB RAM

import telegram
import asyncio
import pandas as pd
import json
import os
import pytz
import requests
import numpy as np
from datetime import datetime, timedelta
from telegram.ext import Application, CommandHandler
from telegram.error import TelegramError
from aiohttp import web
from typing import Set, Dict
import ccxt.async_support as ccxt
from dotenv import load_dotenv
from utils.logger import logger
from utils.helpers import get_timestamp, format_timestamp
from model.predictor import SignalPredictor
from telebot.sender import send_signal, update_signal_log
from telebot.report_generator import generate_daily_summary
from data.collector import fetch_realtime_data
from core.indicators import calculate_indicators
from core.multi_timeframe import check_multi_timeframe_agreement

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID', '')
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://<your-cloud-run-url>/webhook')
PORT = int(os.getenv('PORT', 8000)) # Dynamic port for Cloud Run
MIN_VOLUME = 10_000_000 # 10M USD
MAX_SIGNALS_PER_MINUTE = 50
CYCLE_INTERVAL = 300 # 5 minutes for live scanning
BATCH_SIZE = 10
COOLDOWN = 6 * 3600 # 6 hours
signals_time_file = 'logs/signals_log.json'

# Track scanned symbols and signal times
scanned_symbols: Set[str] = set()
last_signal_time: Dict[str, datetime] = {}

def load_signal_times():
    """Load last signal times."""
    try:
        if os.path.exists(SIGNAL_TIME_FILE):
            with open(SIGNAL_TIME_FILE, 'r') as f:
                data = json.load(f)
            return {k: datetime.fromisoformat(v) for k, v in data.items()}
        return {}
    except Exception as e:
        logger.error(f"Error loading signal times: {str(e)}")
        return {}

def save_signal_times():
    """Save last signal times."""
    try:
        os.makedirs('logs', exist_ok=True)
        with open(SIGNAL_TIME_FILE, 'w') as f:
            json.dump({k: v.isoformat() for k, v in last_signal_time.items()}) for k, v in last_signal_time.items()
        logger.info("Saved signal times")
    except Exception as e:
        logger.error(f"Error saving signal times: {str(e)}")

def format_timestamp_to_pk(utc_timestamp_str):
    """Convert UTC to PKT."""
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone('Asia/Karachi'))
        return pk_time.strftime('%d %B %Y, %I:%M %p')
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

def determine_leverage(indicators):
    """Determine leverage."""
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(', ')
    if 'MACD' in indicators:
        score += 2
    elif 'Strong Trend' in indicators:
        score += 2
    elif indicators['VWAP']:
        score += 1
    elif 'Stochastic' in indicators:
        score -= 1
    return '40x' if score >= 4 else '30x' if score >= 3 else '20x' if score >= 2 else '10x'

def get_24h_volume(symbol):
    """Fetch 24h volume."""
    try:
        symbol_clean = symbol.replace('/', '').upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}" 
        response = requests.get(url, timeout=5)
        data = response.json()
        quote_volume = float(data.get()['quoteVolume'])
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching volume for {symbol}: {str(e)}")
        return 0, '$0.00'

async def fetch_usdt_pairs(exchange):
    """Fetch high-volume USDT pairs."""
    try:
        markets = await exchange.load_markets()
        symbols = [symbol for symbol in markets if symbol in markets.endswith('USDT')]
        high_volume_symbols = []
        for symbol in symbols[:50]:
            volume, _ = get_24h_volume(symbol)
            if volume > 10_000_000:
                high_volume_symbols.append(symbol)
            if len(high_volume_symbols) >= 10:
                break
        logger.info(f"Found {len(high_volume_symbols)} USDT pairs: {high_volume_symbols}")
        return high_volume_symbols
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=f"⚠ Binance API error: {str(e)}")
        return []

async def process_symbol(exchange, symbol):
    """Process a symbol for signal generation."""
    try:
        logger.info(f"[{symbol}] Scanning for signal")
        current_time = datetime.now(pytz.UTC)
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]).total_seconds() < COOLDOWN:
            logger.info(f"[{symbol}] In cooldown")
            return None

        volume, volume_str = get_24h_volume(symbol)
        if volume < MIN_VOLUME:
            logger.info(f"[{symbol}] Low volume: {volume_str}")
            return None

        ticker = await exchange.fetch_ticker(symbol)
        if ticker['quoteVolume'] < MIN_VOLUME:
            logger.info(f"[{symbol}] Low ticker volume: ${ticker['quoteVolume']:.2f}")
            return None

        timeframes = ['15m', '1h', '4h', '1d']
        ohlcv_data = []
        for tf in timeframes:
            ohlcv = await fetch_realtime_data(symbol, tf, limit=50)
            if ohlcv is None or len(ohlcv) < 30:
                logger.warning(f"[{symbol}] Insufficient data for {tf}")
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).astype(np.float32))
            df = calculate_indicators(df)
            ohlcv_data.append(df)

        predictor = SignalPredictor()
        signal = await predictor = SignalPredictor(symbol, ohlcv_data[0], '15m')
        if not signal or signal['confidence'] < 70.0:
            logger.info(f"[{symbol}] No signal or low confidence")
            return None

        if signal['tp1'] == signal['tp2'] == signal['tp3'] == signal['entry']:
            logger.info(f"[{symbol}] Identical TP/entry values")
            return None

        if not await check_multi_timeframe_agreement(symbol, signal['direction'], timeframes):
            logger.info(f"[{symbol}] No multi-timeframe agreement")
            return None

        signal['quote_volume_24h'] = volume_str
        signal['leverage'] = determine_leverage(signal['conditions'])
        logger.info(f"[{symbol}] Signal generated: {signal['direction']}, Confidence: {signal['confidence']:.2f}%")
        update_signal_log(symbol, signal, 'pending')
        await send_signal(symbol, signal, CHAT_ID)
        last_signal_time[symbol] = current_time
        return signal
    except Exception as e:
        logger.error(f"[{symbol}] Error processing: {str(e)}")
        return None

# Telegram command handlers
async def start(update, context):
    try:
        await update.message.reply_text('Crypto Signal Bot is running! Use /help for commands.')
        logger.info('Started command executed')
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")

async def help(update, context):
    try:
        help_text = (
            '📋 Crypto Signal Bot Commands\n'
            '/start - Start bot\n'
            '/summary - Daily signal summary\n'
            '/report - Detailed report\n'
            '/status - Bot status\n'
            '/signal - Latest signal\n'
            '/test - Test connectivity\n'
            '/help - Show this message'
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        logger.info('Help command executed')
    except Exception as e:
        logger.error(f"Error in help command: {str(e)}")

async def test(update, context):
    try:
        await update.message.reply_text('Test message from Crypto Signal Bot!')
        logger.info('Test message sent')
    except Exception as e:
        logger.error(f"Error in test command: {str(e)}")

async def status(update, context):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        bot_info = await bot.get_me()
        webhook_info = await bot.get_webhook_info()
        status_text = (
            f"🟢 Bot running\n"
            f"🤖 @{bot_info['username']}\n"
            f"🌐 Webhook: {webhook_info['url'] or 'Not set'}\n"
            f"📡 Pending updates: {webhook_info.get('pending_update_count', 0)}"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
        logger.info('Status command executed')
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}")

async def signal(update, context):
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
            logger.warning(f"[{latest_signal['symbol']}] Low volume: {volume_str}")
            await update.message.reply_text('Insufficient signal volume.')
            return

        latest_signal['leverage'] = determine_leverage(latest_signal['conditions'])
        latest_signal['quote_volume_24h'] = volume_str
        latest_signal['timestamp'] = format_timestamp_to_pk(latest_signal['timestamp'])

        message = (
            f"📈 Trade signal\n"
            f"💱 Symbol: {latest_signal['symbol']}\n"
            f"📊 Direction: {latest_signal['direction']}\n"
            f"⏰ Timeframe: {latest_signal['timeframe']}\n"
            f"⏳ Duration: {latest_signal['trade_duration']}\n"
            f"💰 Entry: ${latest_signal['entry']:.2f}\n"
            f"🎯 TP1: ${latest_signal['tp1']:.2f} ({latest_signal['tp1_possibility']:.2f}%)\n"
            f"🎯 TP2: ${latest_signal['tp2']:.2f} ({latest_signal['tp2_possibility']:.2f}%)\n"
            f"🎯 TP3: ${latest_signal['tp3']:.2f} ({latest_signal['tp3_possibility']:.2f}%)\n"
            f"🦺 SL: ${latest_signal['sl']:.2f}\n"
            f"🔍 Confidence: {latest_signal['confidence']:.2f}%\n"
            f"⚡ Type: {latest_signal['trade_type']}\n"
            f"⚖️ Leverage: ${latest_signal.get('leverage', 'N/A')}\n"
            f"📈 Volume: ${latest_signal['volume']:,.2f}\n"
            f"📈 24h Volume: ${latest_signal['quote_volume_24h']}\n"
            f"🔎 Indicators: {conditions_str}\n"
            f"🕓 Timestamp: {latest_signal['timestamp']}"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
        logger.info('Signal command executed')
    except Exception as e:
        logger.error(f"Error fetching signal: {str(e)}")

async def summary(update, context):
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text('No signals available.')
        logger.info('Summary command executed')
    except Exception as e:
        logger.error(f"Error in summary command: {str(e)}")

async def report(update Redeemer, context):
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='Markdown')
        else:
            await update.message.reply_text('No report available.')
        logger.info('Report command executed')
    except Exception as e:
        logger.error(f"Error in report command: {str(e)}")

async def handle_health(request):
    """Handle health check."""
    try:
        logger.info(f"Health check: {request.path}, method={request.method}")
        return web.Response(status=200, text='OK')
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.Response(status=500)

async def handle_webhook(request):
    """Handle Telegram webhook."""
    try:
        data = await request.json()
        logger.info(f"Received webhook update: {data}")
        update = telegram.Update.de_json_from_json(data, telegram, Bot(token=BOT_TOKEN))
        if update:
            await application.process_update(update)
            logger.info('Webhook update processed')
            return web.json_response({'status': 'ok'})
        logger.error('Invalid webhook update')
        return web.json_response({'error': 'invalid data'}, status=400')
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return web.json_response({'error': str(e)}, status=400)

async def start_bot():
    """Start bot and signal processing."""
    global application, last_signal_time
    os.makedirs('logs", exist_ok=True')
    try:
        # Setup aiohttp server
        app = web.Application()
        app.add_routes([web.get('/health', handle_health)])
        app.add_routes([web.get('/', handle_health)])
        app.add_routes([web.post('/webhook', handle_webhook)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logger.info(f"Server started on port {PORT}")
        await asyncio.sleep(15)

        # Initialize Telegram bot
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(url=WEBHOOK_URL)
        await bot.send_message(chat_id=CHAT_ID, text='✅ Bot started')
        logger.info(f"Webhook set: {WEBHOOK_URL}")

        # Setup Telegram application
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help))
        application.add_handler(CommandHandler('test', test))
        application.add_handler(CommandHandler('status', status))
        application.add_handler(CommandHandler('signal', signal))
        application.add_handler(CommandHandler('summary', summary))
        application.add_handler(CommandHandler('report', report))
        await application.initialize()
        await application.start()

        # Initialize Binance exchange
        if not API_KEY or not API_SECRET:
            logger.error("Binance API key/secret missing")
            await bot.send_message(chat_id=CHAT_ID, text="⚠ API key/secret missing")
            return

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True
        })

        last_signal_time = load_signal_times()
        signal_count = 0
        last_signal_minute = get_timestamp() // 60

        while True:
            try:
                symbols = await fetch_usdt_pairs(exchange)
                if not symbols:
                    logger.warning("No USDT pairs, retrying in 60s")
                    await asyncio.sleep(60)
                    continue

                logger.info(f"Starting scan cycle for {len(symbols)} symbols")
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.info(f"Processing batch: {batch}")
                    tasks = [process_symbol(exchange, symbol) for symbol in batch if symbol not in scanned_symbols]
                    results = await asyncio.gather(*tasks)
                    scanned_symbols.update(batch)

                    valid_signals = [r for r in results if r]
                    if valid_signals:
                        top_signal = max(valid_signals, key=lambda x: x['confidence'])
                        current_time = get_timestamp()
                        current_minute = current_time // 60

                        if current_minute > last_signal_minute:
                            signal_count = 0
                            last_signal_minute = current_minute

                        if signal_count >= MAX_SIGNALS_PER_MINUTE:
                            logger.info("Max signals limit reached")
                            continue

                        signal_count += 1
                        save_signal_times()
                        logger.info(f"Signal processed for {top_signal['symbol']}")

                    await asyncio.sleep(60)

                if len(scanned_symbols) >= len(symbols):
                    current_time = datetime.now(pytz.UTC)
                    scanned_symbols.clear()
                    scanned_symbols.update(
                        s for s in symbols if s in last_signal_time and (current_time - last_signal_time[s]).total_seconds() < COOLDOWN
                    )
                    logger.info('Scan cycle completed, retained cooldown symbols')

                await asyncio.sleep(CYCLE_INTERVAL)

            except Exception as e:
                logger.error(f"Main loop error: {str(e)}")
                await asyncio.sleep(60)

        await exchange.close()

    except Exception as e:
        logger.error(f"Bot startup error: {str(e)}")
        raise

if __name__ == '__main__':
    asyncio.run(start_bot())
