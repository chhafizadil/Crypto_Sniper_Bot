# Core trading engine for signal generation and execution
# Aligned with merged files (indicators.py, predictor.py, sender.py, multi_timeframe.py)
# Changes:
# - Retained original logic (batch processing, volume checks, multi-timeframe analysis)
# - Integrated with merged predictor.py for ML and rule-based signals
# - Used indicators.py for technical indicators
# - Ensured real-time entry price from collector.py
# - Fixed import and dependency issues

import asyncio
import ccxt.async_support as ccxt
from typing import Dict, List, Set
from core.indicators import calculate_indicators
from core.multi_timeframe import check_multi_timeframe_agreement
from model.predictor import SignalPredictor
from telebot.sender import send_signal
from utils.helpers import get_timestamp
from utils.logger import logger
from dotenv import load_dotenv
import json
import os

# Load environment variables
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Track scanned symbols and signal times
scanned_symbols: Set[str] = set()
last_signal_time: Dict[str, float] = {}
BATCH_SIZE = 20
COOLDOWN = 6 * 3600
CYCLE_INTERVAL = 1200
MAX_SIGNALS_PER_MINUTE = 1
SIGNAL_TIME_FILE = "last_signal_times.json"

def load_signal_times():
    # Load last signal times from JSON
    if os.path.exists(SIGNAL_TIME_FILE):
        with open(SIGNAL_TIME_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_signal_times():
    # Save last signal times to JSON
    with open(SIGNAL_TIME_FILE, 'w') as f:
        json.dump(last_signal_time, f)

async def fetch_usdt_pairs(exchange: ccxt.binance) -> List[str]:
    # Fetch all USDT trading pairs
    try:
        markets = await exchange.load_markets()
        usdt_pairs = [symbol for symbol in markets if symbol.endswith('USDT')]
        logger.info(f"Found {len(usdt_pairs)} USDT pairs")
        return usdt_pairs
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        return []

async def process_symbol(exchange: ccxt.binance, symbol: str) -> Dict:
    # Process a single symbol for signal generation
    try:
        ticker = await exchange.fetch_ticker(symbol)
        volume_usd = ticker['quoteVolume']
        if volume_usd < 2_000_000:
            logger.info(f"[{symbol}] Low volume (${volume_usd:.2f} < $2M)")
            return None

        timeframes = ['15m', '1h', '4h', '1d']
        ohlcv_data = []
        for tf in timeframes:
            ohlcv = await fetch_realtime_data(symbol, tf, limit=50)
            if ohlcv is None or len(ohlcv) < 30:
                logger.warning(f"[{symbol}] Insufficient data for {tf}")
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = calculate_indicators(df)
            ohlcv_data.append(df)

        predictor = SignalPredictor()
        signal = await predictor.predict_signal(symbol, ohlcv_data[0], '15m')
        if not signal or signal['confidence'] < 70.0:
            logger.info(f"[{symbol}] No signal or low confidence")
            return None

        if signal['tp1'] == signal['tp2'] == signal['tp3'] == signal['entry']:
            logger.info(f"[{symbol}] Identical TP/entry values")
            return None

        current_time = get_timestamp()
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]) < COOLDOWN:
            logger.info(f"[{symbol}] In cooldown")
            return None

        if not await check_multi_timeframe_agreement(symbol, signal['direction'], timeframes):
            logger.info(f"[{symbol}] No multi-timeframe agreement")
            return None

        return {'symbol': symbol, 'signal': signal, 'confidence': signal['confidence']}

    except Exception as e:
        logger.error(f"[{symbol}] Error processing: {e}")
        return None

async def main():
    # Main loop to process USDT pairs
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
    })

    global last_signal_time
    last_signal_time = load_signal_times()

    signal_count = 0
    last_signal_minute = get_timestamp() // 60

    while True:
        try:
            usdt_pairs = await fetch_usdt_pairs(exchange)
            for i in range(0, len(usdt_pairs), BATCH_SIZE):
                batch = usdt_pairs[i:i + BATCH_SIZE]
                tasks = [process_symbol(exchange, symbol) for symbol in batch if symbol not in scanned_symbols]
                results = await asyncio.gather(*tasks)
                scanned_symbols.update(batch)

                valid_signals = [r for r in results if r is not None]
                if valid_signals:
                    top_signal = max(valid_signals, key=lambda x: x['confidence'])
                    current_time = get_timestamp()
                    current_minute = current_time // 60

                    if current_minute > last_signal_minute:
                        signal_count = 0
                        last_signal_minute = current_minute

                    if signal_count >= MAX_SIGNALS_PER_MINUTE:
                        logger.info("Max signals per minute reached")
                        continue

                    symbol = top_signal['symbol']
                    signal = top_signal['signal']
                    await send_signal(symbol, signal, TELEGRAM_CHAT_ID)
                    last_signal_time[symbol] = current_time
                    save_signal_times()
                    signal_count += 1
                    logger.info(f"[{symbol}] Signal sent successfully")

                await asyncio.sleep(60)

            if len(scanned_symbols) >= len(usdt_pairs):
                current_time = get_timestamp()
                scanned_symbols.clear()
                scanned_symbols.update(
                    s for s in usdt_pairs if s in last_signal_time and (current_time - last_signal_time[s]) < COOLDOWN
                )
                logger.info("Completed cycle, retained cooldown symbols")

            await asyncio.sleep(CYCLE_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            await asyncio.sleep(60)

    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
