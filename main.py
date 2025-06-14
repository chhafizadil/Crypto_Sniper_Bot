import asyncio
import pandas as pd
import os
import pytz
import requests
import numpy as np
from datetime import datetime, timedelta
from fastapi import FastAPI
from telegram import Bot
from telegram.ext import Application, CommandHandler
import ccxt.async_support as ccxt
from dotenv import load_dotenv
from utils.logger import logger
from utils.helpers import get_timestamp, format_timestamp, is_cooldown_active, scan_pause
from model.predictor import SignalPredictor
from telebot.sender import send_signal, update_signal_log
from telebot.report_generator import generate_daily_summary
from data.collector import fetch_realtime_data
from core.indicators import calculate_indicators
from core.multi_timeframe import check_multi_timeframe_agreement
import uvicorn

load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
PORT = int(os.getenv('PORT', 8080))
MIN_VOLUME = 100_000
MAX_SIGNALS_PER_MINUTE = 10
CYCLE_INTERVAL = 300
BATCH_SIZE = 5
COOLDOWN = 4 * 3600

scanned_symbols = set()
last_signal_time = {}

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Crypto Signal Bot is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone('Asia/Karachi'))
        return pk_time.strftime('%d %B %Y, %I:%M %p')
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

def determine_leverage(indicators):
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
    try:
        markets = await exchange.load_markets()
        symbols = [symbol for symbol in markets if symbol.endswith('USDT')]
        high_volume_symbols = []
        for symbol in symbols:
            volume, _ = get_24h_volume(symbol)
            if volume > MIN_VOLUME:
                high_volume_symbols.append(symbol)
        logger.info(f"Found {len(high_volume_symbols)} USDT pairs with volume > ${MIN_VOLUME:,}")
        return high_volume_symbols
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=f"⚠ Binance API error: {str(e)}")
        return []

async def process_symbol(exchange, symbol):
    try:
        logger.info(f"[{symbol}] Scanning for signal")
        current_time = datetime.now(pytz.UTC)
        if is_cooldown_active(symbol, last_signal_time, COOLDOWN):
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
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']).astype(np.float32)
            df = calculate_indicators(df)
            ohlcv_data.append(df)

        predictor = SignalPredictor()
        signal = await predictor.predict_signal(symbol, ohlcv_data[0], '15m')
        if not signal or signal['confidence'] < 50.0:
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

async def start(update, context):
    try:
        await update.message.reply_text('Crypto Signal Bot is running! Use /help for commands.')
        logger.info('Start command executed')
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
        bot = Bot(token=BOT_TOKEN)
        bot_info = await bot.get_me()
        status_text = (
            f"🟢 Bot running\n"
            f"🤖 @{bot_info.username}\n"
            f"📡 Symbols scanned: {len(scanned_symbols)}\n"
            f"📈 Active signals: {len(last_signal_time)}"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
        logger.info('Status command executed')
    except Exception as e:
        logger.error(f"Error in status: {str(e)}")

async def signal(update, context):
    try:
        if not hasattr(update_signal_log, 'signals_data') or not update_signal_log.signals_data:
            await update.message.reply_text('No signals available.')
            return
        latest_signal = update_signal_log.signals_data[-1]
        conditions_str = ', '.join(latest_signal['conditions'])
        volume, volume_str = get_24h_volume(latest_signal['symbol'])
        if volume < MIN_VOLUME:
            logger.warning(f"[{latest_signal['symbol']}] Low volume: {volume_str}")
            await update.message.reply_text('Insufficient signal volume.')
            return

        latest_signal['leverage'] = determine_leverage(latest_signal['conditions'])
        latest_signal['quote_volume_24h'] = volume_str
        latest_signal['timestamp'] = format_timestamp_to_pk(latest_signal['timestamp'])

        message = (
            f"📈 Trading signal\n"
            f"💱 Symbol: {latest_signal['symbol']}\n"
            f"📊 Direction: {latest_signal['direction']}\n"
            f"⏰ Timeframe: {latest_signal['timeframe']}\n"
            f"⏳ Duration: {latest_signal['trade_duration']}\n"
            f"💰 Entry: ${latest_signal['entry_price']:.2f}\n"
            f"🎯 TP1: ${latest_signal['tp1']:.2f} ({latest_signal['tp1_possibility']:.2f}%)\n"
            f"🎯 TP2: ${latest_signal['tp2']:.2f} ({latest_signal['tp2_possibility']:.2f}%)\n"
            f"🎯 TP3: ${latest_signal['tp3']:.2f} ({latest_signal['tp3_possibility']:.2f}%)\n"
            f"🛑 SL: ${latest_signal['sl']:.2f}\n"
            f"🔍 Confidence: {latest_signal['confidence']:.2f}%\n"
            f"⚡ Type: {latest_signal['trade_type']}\n"
            f"⚖ Leverage: {latest_signal.get('leverage', 'N/A')}\n"
            f"📈 Volume: ${latest_signal['volume']:.2f}\n"
            f"📈 24h Volume: {latest_signal['quote_volume_24h']}\n"
            f"🔎 Indicators: {conditions_str}\n"
            f"🕒 Timestamp: {latest_signal['timestamp']}"
        )
        await update.message.reply_text(message, parse_mode='markdown')
        logger.info('Signal command executed')
    except Exception as e:
        logger.error(f"Error handling signal: {str(e)}")

async def summary(update, context):
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='markdown')
        else:
            await update.message.reply_text('No signals available.')
        logger.info('Summary command executed')
    except Exception as e:
        logger.error(f"Error in summary: {str(e)}")

async def report(update, context):
    try:
        report = await generate_daily_summary()
        if report:
            await update.message.reply_text(report, parse_mode='markdown')
        else:
            await update.message.reply_text('No signals available.')
        logger.info('Report command executed')
    except Exception as e:
        logger.error(f"Error in report: {str(e)}")

async def start_bot():
    global application, last_signal_time
    try:
        if not API_KEY or not API_SECRET:
            logger.error("Binance API key/secret missing")
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(chat_id=CHAT_ID, text="⚠️ API key missing")
            return

        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True
        })

        last_signal_time = {}
        signal_count = 0
        last_signal_minute = get_timestamp() // 60

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
        await application.updater.start_polling()

        while True:
            try:
                symbols = await fetch_usdt_pairs(exchange)
                if not symbols:
                    logger.warning("No USDT pairs found, retrying in 60s")
                    await asyncio.sleep(60)
                    continue

                logger.info(f"Starting scan cycle for {len(symbols)} symbols")
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch: {batch}")
                    tasks = [
                        process_symbol(exchange, symbol)
                        for symbol in batch
                        if not is_cooldown_active(symbol, last_signal_time, COOLDOWN)
                    ]
                    results = await asyncio.gather(*tasks)
                    scanned_symbols.update(batch)

                    valid_signals = [r for r in results if r]
                    if valid_signals:
                        current_time = get_timestamp()
                        current_minute = current_time // 60

                        if current_minute > last_signal_minute:
                            signal_count = 0
                            last_signal_minute = current_minute

                        if signal_count >= MAX_SIGNALS_PER_MINUTE:
                            logger.info("Max signals limit reached")
                            continue

                        signal_count += len(valid_signals)
                        logger.info(f"Processed {len(valid_signals)} signals in batch")

                    await asyncio.sleep(5)

                scanned_symbols.clear()
                logger.info("Scan cycle completed, pausing for 5 minutes")
                await scan_pause(CYCLE_INTERVAL)

            except Exception as e:
                logger.error(f"Main loop error: {str(e)}")
                await asyncio.sleep(60)

        await exchange.close()

    except Exception as e:
        logger.error(f"Bot startup error: {str(e)}")
        raise

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
