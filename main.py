# Updated main.py to add zero price/volume checks, simplify logging, and ensure stable processing
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import os
from fastapi import FastAPI
from datetime import datetime, timedelta
from core.analysis import analyze_symbol_multi_timeframe
from telebot.sender import send_signal, start_bot
from utils.logger import logger

app = FastAPI()

MIN_QUOTE_VOLUME = 500000
MIN_CONFIDENCE = 40  # Lowered to match soft conditions
COOLDOWN_HOURS = 6

cooldowns = {}

def save_signal_to_csv(signal):
    try:
        os.makedirs('logs', exist_ok=True)
        file_path = 'logs/signals_log_new.csv'
        df = pd.DataFrame([signal])
        df.to_csv(file_path, mode='a', index=False, 
                  header=not os.path.exists(file_path))
        logger.info(f"Signal saved to CSV: {signal['symbol']} at {signal['timestamp']}")
    except Exception as e:
        logger.error(f"Error saving signal to CSV for {signal['symbol']}: {str(e)}")

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
        signals = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
        for timeframe, signal in signals.items():
            if signal and signal['confidence'] >= MIN_CONFIDENCE:
                signal['timestamp'] = datetime.now().isoformat()
                signal['status'] = 'pending'
                signal['hit_timestamp'] = None
                await send_signal(signal)
                save_signal_to_csv(signal)
                update_cooldown(symbol)
                logger.info(f"✅ Signal generated for {symbol} ({timeframe}): {signal['direction']} (Confidence: {signal['confidence']:.1f}%, Entry: {signal['entry']:.4f}, TP1: {signal['tp1']:.4f}, TP2: {signal['tp2']:.4f}, TP3: {signal['tp3']:.4f}, SL: {signal['sl']:.4f}, Conditions: {', '.join(signal['conditions'])})")
                break
    except Exception as e:
        logger.error(f"[{symbol}] Error processing symbol: {str(e)}")

async def get_high_volume_symbols(exchange, min_volume):
    symbols = [s for s in exchange.symbols if s.endswith('/USDT')]
    high_volume_symbols = []
    async def fetch_ticker(symbol):
        try:
            ticker = await exchange.fetch_ticker(symbol)
            quote_volume = ticker.get('quoteVolume', 0)
            close_price = ticker.get('close', 0)
            if quote_volume is not None and quote_volume >= min_volume and close_price > 0.01:  # Zero price check
                return symbol, quote_volume
            else:
                logger.warning(f"[{symbol}] Skipped: Low volume (${quote_volume:,.2f} < ${min_volume:,.0f}) or zero price ({close_price})")
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

async def main_loop():
    try:
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True
        })
        await exchange.load_markets()
        logger.info("Binance API connection successful")
        timeframes = ['15m', '1h', '4h', '1d']
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
            logger.info("Completed analysis cycle. Waiting 180 seconds for next cycle...")
            await asyncio.sleep(180)
    except Exception as e:
        logger.error(f"Error in main loop: {str(e)}")
    finally:
        await exchange.close()

@app.on_event("startup")
async def startup_event():
    logger.info("Starting bot...")
    asyncio.create_task(start_bot())
    asyncio.create_task(main_loop())

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

async def test_analysis():
    symbol = "ADA/USDT"
    exchange = ccxt.binance({"enableRateLimit": True})
    timeframes = ["15m"]
    logger.info(f"Testing analysis for {symbol}")
    signals = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
    logger.info(f"Test analysis results for {symbol}: {signals}")
    await exchange.close()

if __name__ == "__main__":
    asyncio.run(test_analysis())
