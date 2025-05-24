import asyncio
import ccxt.async_support as ccxt
from typing import Dict, List, Set
from core.indicators import calculate_indicators
from core.multi_timeframe import multi_timeframe_analysis
from model.predictor import predict_signal
from telebot.sender import send_signal
import os
import json
import logging
from queue import PriorityQueue

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
# Batch delay (60 seconds)
BATCH_DELAY = 60
# Signal queue to prioritize high-confidence signals
signal_queue = PriorityQueue()
# Maximum signals per hour
MAX_SIGNALS_PER_HOUR = 10
# Signal count in current hour
hourly_signal_count = 0
# Last hour timestamp
last_hour = 0

# Load/save last_signal_time to file for persistence
LAST_SIGNAL_FILE = "last_signal_time.json"

def load_last_signal_time():
    """Load last signal times from file."""
    global last_signal_time
    try:
        if os.path.exists(LAST_SIGNAL_FILE):
            with open(LAST_SIGNAL_FILE, 'r') as f:
                last_signal_time = {k: float(v) for k, v in json.load(f).items()}
                logger.debug(f"Loaded last signal times: {len(last_signal_time)} symbols")
    except Exception as e:
        logger.error(f"Error loading last signal times: {str(e)}")

def save_last_signal_time():
    """Save last signal times to file."""
    try:
        with open(LAST_SIGNAL_FILE, 'w') as f:
            json.dump(last_signal_time, f)
            logger.debug("Saved last signal times")
    except Exception as e:
        logger.error(f"Error saving last signal times: {str(e)}")

async def fetch_usdt_pairs(exchange: ccxt.binance) -> List[str]:
    """Fetch all USDT trading pairs."""
    markets = await exchange.load_markets()
    usdt_pairs = [symbol for symbol in markets if symbol.endswith('USDT')]
    logger.info(f"Found {len(usdt_pairs)} USDT pairs")
    return usdt_pairs

async def process_symbol(exchange: ccxt.binance, symbol: str) -> Dict:
    """Process a single symbol for signal generation and return signal if valid."""
    try:
        # Fetch ticker for volume check
        ticker = await exchange.fetch_ticker(symbol)
        volume_usd = ticker['quoteVolume']
        volume_threshold = float(os.getenv('VOLUME_THRESHOLD', 2000000))
        if volume_usd < volume_threshold:
            logger.info(f"Rejecting {symbol}: Low volume (${volume_usd:.2f} < ${volume_threshold})")
            return None

        # Fetch OHLCV data for multiple timeframes
        timeframes = ['15m', '1h', '4h', '1d']
        ohlcv_data = {}
        for tf in timeframes:
            ohlcv = await exchange.fetch_ohlcv(symbol, tf, limit=100)
            ohlcv_data[tf] = ohlcv

        # Calculate indicators
        indicators = calculate_indicators(ohlcv_data)

        # Perform multi-timeframe analysis
        analysis_result = multi_timeframe_analysis(indicators, ohlcv_data)

        # Check agreement threshold
        agreement_threshold = float(os.getenv('AGREEMENT_THRESHOLD', 85))
        if analysis_result['agreement'] < agreement_threshold:
            logger.info(f"Rejecting {symbol}: Low timeframe agreement ({analysis_result['agreement']}% < {agreement_threshold}%)")
            return None

        # Predict signal
        signal = await predict_signal(symbol, ohlcv_data, indicators, analysis_result)
        if not signal:
            logger.info(f"No signal for {symbol}")
            return None

        # Check for duplicate TP/SL values
        if signal['tp1'] == signal['tp2'] == signal['tp3'] == signal['entry']:
            logger.info(f"Rejecting {symbol}: Identical entry and TP values")
            return None

        # Check cooldown
        from utils.helpers import get_timestamp
        current_time = get_timestamp()
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]) < COOLDOWN:
            logger.info(f"Rejecting {symbol}: In cooldown")
            return None

        # Check minimum confidence
        min_confidence = float(os.getenv('MIN_CONFIDENCE', 70.0))
        if signal['confidence'] < min_confidence:
            logger.info(f"Rejecting {symbol}: Low confidence ({signal['confidence']}% < {min_confidence}%)")
            return None

        return signal

    except Exception as e:
        logger.error(f"Error processing {symbol}: {str(e)}")
        return None

async def process_signal_queue(exchange: ccxt.binance):
    """Process the signal queue every 5 minutes, sending the highest-confidence signal."""
    from utils.helpers import get_timestamp
    global hourly_signal_count, last_hour
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    while True:
        current_time = get_timestamp()
        current_hour = int(current_time // 3600)

        # Reset hourly signal count if new hour
        if current_hour != last_hour:
            hourly_signal_count = 0
            last_hour = current_hour
            logger.debug("Reset hourly signal count")

        # Check if max signals per hour reached
        if hourly_signal_count >= MAX_SIGNALS_PER_HOUR:
            logger.info(f"Max signals per hour ({MAX_SIGNALS_PER_HOUR}) reached, waiting...")
            await asyncio.sleep(3600 - (current_time % 3600))
            continue

        # Get the highest-confidence signal from queue
        if not signal_queue.empty():
            # PriorityQueue uses (priority, item), where lower priority is better
            _, signal = signal_queue.get()
            symbol = signal['symbol']
            try:
                await send_signal(symbol, signal, chat_id)
                last_signal_time[symbol] = current_time
                save_last_signal_time()
                hourly_signal_count += 1
                logger.info(f"Signal sent from queue: {symbol} - {signal['direction']} ✔ (Hourly count: {hourly_signal_count})")
            except Exception as e:
                logger.error(f"Error sending queued signal for {symbol}: {str(e)}")
        else:
            logger.debug("Signal queue empty")

        # Wait 5 minutes before processing next signal
        await asyncio.sleep(300)

async def main():
    """Main loop to process USDT pairs in batches and queue signals."""
    exchange = ccxt.binance({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_API_SECRET'),
        'enableRateLimit': True,
    })

    # Load last signal times
    load_last_signal_time()

    # Start signal queue processor
    asyncio.create_task(process_signal_queue(exchange))

    while True:
        try:
            # Fetch USDT pairs
            usdt_pairs = await fetch_usdt_pairs(exchange)

            # Process symbols in batches
            for i in range(0, len(usdt_pairs), BATCH_SIZE):
                batch = usdt_pairs[i:i + BATCH_SIZE]
                signals = []
                for symbol in batch:
                    if symbol not in scanned_symbols:
                        signal = await process_symbol(exchange, symbol)
                        if signal:
                            # Add to queue with negative confidence as priority (lower is better)
                            signal_queue.put((-signal['confidence'], signal))
                            logger.debug(f"Queued signal for {symbol}: Confidence {signal['confidence']}%")
                    scanned_symbols.add(symbol)

                # Add delay after each batch
                logger.debug(f"Waiting {BATCH_DELAY} seconds after batch")
                await asyncio.sleep(BATCH_DELAY)

            # Clear scanned symbols after full cycle
            if len(scanned_symbols) >= len(usdt_pairs):
                scanned_symbols.clear()
                logger.info("Completed full cycle, resetting scanned symbols")

            # Wait for next cycle
            logger.debug(f"Waiting {CYCLE_INTERVAL} seconds for next cycle")
            await asyncio.sleep(CYCLE_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            await asyncio.sleep(60)

    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
