import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from typing import Dict, List, Set
from core.indicators import calculate_indicators
from core.multi_timeframe import multi_timeframe_analysis
from model.predictor import SignalPredictor
from telebot.sender import send_signal
from utils.helpers import get_timestamp
from dotenv import load_dotenv
import logging
import json
import os

# Load environment variables
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Set to track scanned symbols in a cycle
scanned_symbols: Set[str] = set()
# Dictionary to track last signal time for each symbol
last_signal_time: Dict[str, float] = {}
# Batch size for processing symbols
BATCH_SIZE = 20
# Cooldown period (6 hours in seconds)
COOLDOWN = 6 * 3600
# Cycle interval (20 minutes in seconds)
CYCLE_INTERVAL = 1200
# Maximum signals per minute
MAX_SIGNALS_PER_MINUTE = 1
# File to store last signal times
SIGNAL_TIME_FILE = "last_signal_times.json"

def load_signal_times():
    """Load last signal times from JSON file."""
    if os.path.exists(SIGNAL_TIME_FILE):
        with open(SIGNAL_TIME_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_signal_times():
    """Save last signal times to JSON file."""
    with open(SIGNAL_TIME_FILE, 'w') as f:
        json.dump(last_signal_time, f)

async def fetch_usdt_pairs(exchange: ccxt.binance) -> List[str]:
    """Fetch all USDT trading pairs."""
    try:
        markets = await exchange.load_markets()
        usdt_pairs = [symbol for symbol in markets if symbol.endswith('/USDT')]
        logger.info(f"Found {len(usdt_pairs)} USDT pairs")
        return usdt_pairs
    except Exception as e:
        logger.error(f"Error fetching USDT pairs: {str(e)}")
        return []

async def process_symbol(exchange: ccxt.binance, symbol: str) -> Dict:
    """Process a single symbol for signal generation and return signal with confidence."""
    try:
        # Fetch ticker for volume check
        ticker = await exchange.fetch_ticker(symbol)
        volume_usd = ticker.get('quoteVolume', 0)
        if volume_usd < 2_000_000:
            logger.info(f"Rejecting {symbol}: Low volume (${volume_usd:.2f} < $2,000,000)")
            return None

        # Fetch OHLCV data for multiple timeframes
        timeframes = ['15m', '1h', '4h', '1d']
        ohlcv_data = {}
        for tf in timeframes:
            ohlcv = await exchange.fetch_ohlcv(symbol, tf, limit=100)
            if not ohlcv or len(ohlcv) < 30:
                logger.warning(f"Insufficient OHLCV data for {symbol} on {tf}: {len(ohlcv)} rows")
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = calculate_indicators(df)
            if df is None:
                logger.warning(f"Failed to calculate indicators for {symbol} on {tf}")
                return None
            ohlcv_data[tf] = df

        # Perform multi-timeframe analysis
        analysis_result = await multi_timeframe_analysis(symbol, ohlcv_data, timeframes)
        if analysis_result is None or analysis_result.get('agreement', 0) < 85:
            logger.info(f"Rejecting {symbol}: Low timeframe agreement ({analysis_result.get('agreement', 0)} < 85%)")
            return None

        # Predict signal using SignalPredictor
        predictor = SignalPredictor()
        signal = await predictor.predict_signal(symbol, ohlcv_data['15m'], '15m')
        if not signal or signal['confidence'] < 70.0:
            logger.info(f"No signal or low confidence for {symbol}")
            return None

        # Check for duplicate TP/SL values
        if signal['tp1'] == signal['tp2'] == signal['tp3'] == signal['entry']:
            logger.info(f"Rejecting {symbol}: Identical entry and TP values")
            return None

        # Check cooldown
        current_time = get_timestamp()
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]) < COOLDOWN:
            logger.info(f"Rejecting {symbol}: In cooldown")
            return None

        return {'symbol': symbol, 'signal': signal, 'confidence': signal['confidence']}

    except Exception as e:
        logger.error(f"Error processing {symbol}: {str(e)}")
        return None

async def main():
    """Main loop to process USDT pairs in batches with signal limiting."""
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
    })

    # Load last signal times
    global last_signal_time
    last_signal_time = load_signal_times()

    signal_count = 0
    last_signal_minute = get_timestamp() // 60

    try:
        while True:
            # Fetch USDT pairs
            usdt_pairs = await fetch_usdt_pairs(exchange)
            if not usdt_pairs:
                logger.error("No USDT pairs found, retrying in 60 seconds")
                await asyncio.sleep(60)
                continue

            # Process symbols in batches
            for i in range(0, len(usdt_pairs), BATCH_SIZE):
                batch = usdt_pairs[i:i + BATCH_SIZE]
                tasks = [process_symbol(exchange, symbol) for symbol in batch if symbol not in scanned_symbols]
                results = await asyncio.gather(*tasks)
                scanned_symbols.update(batch)

                # Filter valid signals and select top confidence
                valid_signals = [r for r in results if r is not None]
                if valid_signals:
                    top_signal = max(valid_signals, key=lambda x: x['confidence'])
                    current_time = get_timestamp()
                    current_minute = current_time // 60

                    # Check signal rate limit
                    if current_minute > last_signal_minute:
                        signal_count = 0
                        last_signal_minute = current_minute

                    if signal_count >= MAX_SIGNALS_PER_MINUTE:
                        logger.info("Max signals per minute reached, skipping")
                        continue

                    # Send top signal
                    symbol = top_signal['symbol']
                    signal = top_signal['signal']
                    await send_signal(symbol, signal, TELEGRAM_CHAT_ID)
                    last_signal_time[symbol] = current_time
                    save_signal_times()
                    signal_count += 1
                    logger.info(f"Signal sent successfully: {symbol} - {signal['direction']} ✔")

                # Delay between batches
                await asyncio.sleep(60)

            # Clear scanned symbols after full cycle
            if len(scanned_symbols) >= len(usdt_pairs):
                current_time = get_timestamp()
                scanned_symbols.clear()
                scanned_symbols.update(
                    s for s in usdt_pairs if s in last_signal_time and (current_time - last_signal_time[s]) < COOLDOWN
                )
                logger.info("Completed full cycle, retaining cooldown symbols")

            # Wait for next cycle (20 minutes)
            await asyncio.sleep(CYCLE_INTERVAL)

    except Exception as e:
        logger.error(f"Main loop error: {str(e)}")
        await asyncio.sleep(60)
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
