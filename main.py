import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import aiosqlite
import os
from fastapi import FastAPI, Request
from datetime import datetime, timedelta
from core.analysis import analyze_symbol_multi_timeframe
from telebot.sender import send_signal, start_bot
from utils.logger import logger
from core.multi_timeframe import multi_timeframe_boost

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Crypto Signal Bot is running. Use /health for status or /webhook for Telegram updates."}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Telegram Update: {data}")
        application = app.state.telegram_application
        await application.process_update(data)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"ok": False}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

MIN_QUOTE_VOLUME = 500000
MIN_CONFIDENCE = 65
COOLDOWN_HOURS = 6

cooldowns = {}

async def init_db():
    try:
        os.makedirs('logs', exist_ok=True)
        async with aiosqlite.connect('logs/signals.db') as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    direction TEXT,
                    entry REAL,
                    confidence REAL,
                    timeframe TEXT,
                    conditions TEXT,
                    tp1 REAL,
                    tp2 REAL,
                    tp3 REAL,
                    sl REAL,
                    tp1_possibility REAL,
                    tp2_possibility REAL,
                    tp3_possibility REAL,
                    volume REAL,
                    trade_type TEXT,
                    trade_duration TEXT,
                    timestamp TEXT,
                    status TEXT,
                    hit_timestamp TEXT,
                    quote_volume_24h TEXT,
                    leverage TEXT,
                    agreement REAL
                )
            ''')
            await db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")

async def save_signal_to_db(signal):
    try:
        conditions_str = ', '.join(signal['conditions']) if isinstance(signal.get('conditions'), list) else signal.get('conditions', '')
        async with aiosqlite.connect('logs/signals.db') as db:
            await db.execute('''
                INSERT INTO signals (
                    symbol, direction, entry, confidence, timeframe, conditions,
                    tp1, tp2, tp3, sl, tp1_possibility, tp2_possibility,
                    tp3_possibility, volume, trade_type, trade_duration, timestamp,
                    status, hit_timestamp, quote_volume_24h, leverage, agreement
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal.get('symbol'), signal.get('direction'), signal.get('entry'),
                signal.get('confidence'), signal.get('timeframe'), conditions_str,
                signal.get('tp1'), signal.get('tp2'), signal.get('tp3'), signal.get('sl'),
                signal.get('tp1_possibility'), signal.get('tp2_possibility'),
                signal.get('tp3_possibility'), signal.get('volume'), signal.get('trade_type'),
                signal.get('trade_duration'), signal.get('timestamp'), signal.get('status'),
                signal.get('hit_timestamp'), signal.get('quote_volume_24h'), signal.get('leverage'),
                signal.get('agreement')
            ))
            await db.commit()
        logger.info(f"Signal saved to database: {signal['symbol']} at {signal['timestamp']}")
    except Exception as e:
        logger.error(f"Error saving signal to database for {signal.get('symbol','unknown')}: {str(e)}")

async def send_signals_from_db():
    try:
        async with aiosqlite.connect('logs/signals.db') as db:
            cursor = await db.execute("SELECT * FROM signals WHERE status = 'pending'")
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(rows, columns=columns)
        for _, signal in df.iterrows():
            signal_dict = signal.to_dict()
            logger.info(f"Sending signal from database: {signal_dict.get('symbol', 'N/A')} - {signal_dict.get('direction', 'N/A')}")
            await send_signal(signal_dict)
            logger.info(f"[{signal_dict.get('symbol', 'N/A')}] Signal sent from database to Telegram")
    except Exception as e:
        logger.error(f"Failed to read database or send signals: {str(e)}")

def is_symbol_on_cooldown(symbol):
    try:
        if symbol in cooldowns:
            last_signal_time = cooldowns[symbol]
            if datetime.now() < last_signal_time + timedelta(hours=COOLDOWN_HOURS):
                logger.info(f"[{symbol}] On cooldown until {last_signal_time + timedelta(hours=COOLDOWN_HOURS)}")
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking cooldown for {symbol}: {str(e)}")
        return False

def update_cooldown(symbol):
    try:
        cooldowns[symbol] = datetime.now()
        logger.info(f"[{symbol}] Cooldown updated until {datetime.now() + timedelta(hours=COOLDOWN_HOURS)}")
    except Exception as e:
        logger.error(f"Error updating cooldown for {symbol}: {str(e)}")

async def process_symbol(symbol, exchange, timeframes):
    try:
        if is_symbol_on_cooldown(symbol):
            logger.info(f"[{symbol}] Skipping due to cooldown")
            return
        logger.info(f"[{symbol}] Starting multi-timeframe analysis")
        signal = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
        if signal and signal['confidence'] >= MIN_CONFIDENCE:
            signals, agreement = await multi_timeframe_boost(symbol, exchange, signal['direction'], timeframes)
            if agreement < 50:  # 2/4 agreement = 75%
                logger.warning(f"[{symbol}] Insufficient timeframe agreement: {agreement:.2f}%")
                return
            signal['timestamp'] = datetime.now().isoformat()
            signal['status'] = 'pending'
            signal['hit_timestamp'] = None
            signal['agreement'] = agreement
            await save_signal_to_db(signal)
            await send_signal(signal)
            update_cooldown(symbol)
            logger.info(f"✅ Signal generated for {symbol} ({signal['timeframe']}): {signal['direction']} (Confidence: {signal['confidence']:.2f}%, Agreement: {agreement:.2f}%)")
        else:
            logger.info(f"[{symbol}] No signal or confidence below threshold ({signal.get('confidence',0) if signal else 'N/A'}%)")
    except Exception as e:
        logger.error(f"[{symbol}] Error processing symbol: {str(e)}")

async def get_high_volume_symbols(exchange, min_volume):
    try:
        await exchange.load_markets(reload=True)
        symbols = [s for s in exchange.markets.keys() if s.endswith('/USDT')]
        logger.info(f"[Main] Loaded {len(symbols)} USDT pairs")
        high_volume_symbols = []
        async def fetch_ticker(symbol):
            try:
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume = float(ticker.get('quoteVolume', 0) or 0)
                close_price = float(ticker.get('close', 0) or 0)
                if quote_volume >= min_volume and 0.00001 < close_price < 100000:
                    return symbol, quote_volume
                else:
                    return None
            except Exception as e:
                logger.error(f"[{symbol}] Error fetching ticker: {str(e)}")
                return None
        batch_size = 25
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tasks = [fetch_ticker(symbol) for symbol in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple):
                    symbol, quote_volume = result
                    high_volume_symbols.append(symbol)
            await asyncio.sleep(3)
        return high_volume_symbols
    except Exception as e:
        logger.error(f"[Main] Error loading markets: {str(e)}")
        return []

async def main_loop():
    try:
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True
        })
        logger.info("Binance API connection successful")
        timeframes = ['15m', '1h', '4h', '1d']
        await init_db()
        while True:
            high_volume_symbols = await get_high_volume_symbols(exchange, MIN_QUOTE_VOLUME)
            logger.info(f"Selected {len(high_volume_symbols)} USDT pairs with volume >= ${MIN_QUOTE_VOLUME:,.0f}")
            if not high_volume_symbols:
                logger.warning("No symbols passed volume filter. Retrying in 180 seconds...")
                await asyncio.sleep(180)
                continue
            batch_size = 1
            selected_symbols = high_volume_symbols[:20]
            for i in range(0, len(selected_symbols), batch_size):
                batch = selected_symbols[i:i + batch_size]
                tasks = [process_symbol(symbol, exchange, timeframes) for symbol in batch]
                await asyncio.gather(*tasks, return_exceptions=True)
                logger.info(f"Completed analysis batch {i//batch_size + 1}/{len(selected_symbols)//batch_size + 1}")
                await asyncio.sleep(15)
            logger.info("Completed analysis cycle. Waiting 180 seconds...")
            await asyncio.sleep(180)
    except Exception as e:
        logger.error(f"Error in main loop: {str(e)}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    logger.info("Starting bot...")
    try:
        application = await start_bot()
        app.state.telegram_application = application
        logger.info("Telegram application stored in app state")
        await send_signals_from_db()
        asyncio.create_task(main_loop())
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
