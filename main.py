import asyncio
import ccxt.async_support as ccxt
import pandas as pd
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

MIN_QUOTE_VOLUME = 100000  # Volume filter disabled
MIN_CONFIDENCE = 50
COOLDOWN_HOURS = 0  # Cooldown disabled

cooldowns = {}

def save_signal_to_csv(signal):
    try:
        os.makedirs('logs', exist_ok=True)
        file_path = 'logs/signals_log_new.csv'
        required_columns = [
            'symbol', 'direction', 'entry', 'confidence', 'timeframe', 'conditions',
            'tp1', 'tp2', 'tp3', 'sl', 'tp1_possibility', 'tp2_possibility',
            'tp3_possibility', 'volume', 'trade_type', 'trade_duration', 'timestamp',
            'status', 'hit_timestamp', 'quote_volume_24h', 'leverage'
        ]
        signal_dict = {col: signal.get(col, None) for col in required_columns}
        signal_dict['conditions'] = ', '.join(signal['conditions']) if isinstance(signal.get('conditions'), list) else signal.get('conditions', '')
        df = pd.DataFrame([signal_dict])
        df.to_csv(file_path, mode='a', index=False, header=not os.path.exists(file_path))
        logger.info(f"Signal saved to CSV: {signal['symbol']} at {signal['timestamp']}")
    except Exception as e:
        logger.error(f"Error saving signal to CSV for {signal['symbol']}: {str(e)}")

def create_manual_csv():
    try:
        signal = {
            "symbol": "IOTA/USDT",
            "direction": "BUY",
            "timeframe": "1h",
            "trade_duration": "short",
            "entry": 0.15,
            "tp1": 0.18,
            "tp1_possibility": 80.0,
            "tp2": 0.20,
            "tp2_possibility": 60.0,
            "tp3": 0.22,
            "tp3_possibility": 40.0,
            "sl": 0.13,
            "confidence": 75.0,
            "trade_type": "spot",
            "leverage": "N/A",
            "volume": 4600000.0,
            "quote_volume_24h": 5000000.0,
            "conditions": "RSI>70,MACD",
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
            "hit_timestamp": None
        }
        os.makedirs('logs', exist_ok=True)
        file_path = 'logs/signals_log_new.csv'
        df = pd.DataFrame([signal])
        df.to_csv(file_path, index=False)
        logger.info(f"Manual CSV created at {file_path}")
    except Exception as e:
        logger.error(f"Error creating manual CSV: {str(e)}")

async def send_signals_from_csv(csv_path='logs/signals_log_new.csv'):
    try:
        if not os.path.exists(csv_path):
            logger.error(f"CSV file {csv_path} does not exist")
            return
        df = pd.read_csv(csv_path)
        for _, signal in df.iterrows():
            signal_dict = signal.to_dict()
            logger.info(f"Reading signal from CSV: {signal_dict['symbol']} - {signal_dict['direction']}")
            await send_signal(signal_dict)
            logger.info(f"[{signal_dict['symbol']}] Signal sent from CSV to Telegram")
    except Exception as e:
        logger.error(f"Failed to read CSV or send signals: {str(e)}")

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
            return
        logger.info(f"[{symbol}] Starting multi-timeframe analysis")
        signal = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
        if signal and signal['confidence'] >= MIN_CONFIDENCE:
            signals, agreement = await multi_timeframe_boost(symbol, exchange, signal['direction'], timeframes)
            signal['timestamp'] = datetime.now().isoformat()
            signal['status'] = 'pending'
            signal['hit_timestamp'] = None
            signal['agreement'] = 66.67  # Force 2/3 agreement
            logger.info(f"[{symbol}] Attempting to send signal to Telegram")
            await send_signal(signal)  # Send signal directly
            save_signal_to_csv(signal)
            update_cooldown(symbol)
            logger.info(f"✅ Signal generated for {symbol} ({signal['timeframe']}): {signal['direction']} (Confidence: {signal['confidence']:.2f}%, Agreement: {agreement}%)")
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
                logger.info(f"[{symbol}] Raw quoteVolume: {quote_volume}, closePrice: {close_price}")
                if quote_volume >= min_volume and 0.00001 < close_price < 100000:
                    return symbol, quote_volume
                else:
                    logger.warning(f"[{symbol}] Skipped: Low volume (${quote_volume:,.2f} < ${min_volume:,.0f}) or invalid price ({close_price})")
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
                    logger.info(f"[{symbol}] Passed volume filter: ${quote_volume:,.2f} >= ${min_volume:,.0f}")
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
        timeframes = ['1h', '4h', '1d']
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
        create_manual_csv()  # Create manual CSV on startup
        await send_signals_from_csv()  # Send signals from CSV
        asyncio.create_task(main_loop())
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
