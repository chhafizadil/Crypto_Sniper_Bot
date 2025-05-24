import asyncio
import ccxt.async_support as ccxt
from typing import Dict, List, Set
from core.indicators import calculate_indicators
from core.multi_timeframe import multi_timeframe_analysis
from model.predictor import predict_signal
from telebot.sender import send_signal
from config.settings import API_KEY, API_SECRET, TELEGRAM_CHAT_ID
from core.utils import get_timestamp
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set to track scanned symbols in a cycle
scanned_symbols: Set[str] = set()
# Dictionary to track last signal time for each symbol
last_signal_time: Dict[str, float] = {}
# Batch size for processing symbols
BATCH_SIZE = 20
# Cooldown period (4 hours in seconds)
COOLDOWN = 4 * 3600
# Cycle interval (10 minutes in seconds)
CYCLE_INTERVAL = 600

async def fetch_usdt_pairs(exchange: ccxt.binance) -> List[str]:
    """Fetch all USDT trading pairs."""
    markets = await exchange.load_markets()
    usdt_pairs = [symbol for symbol in markets if symbol.endswith('USDT')]
    logger.info(f"Found {len(usdt_pairs)} USDT pairs")
    return usdt_pairs

async def process_symbol(exchange: ccxt.binance, symbol: str) -> None:
    """Process a single symbol for signal generation."""
    try:
        # Fetch ticker for volume check
        ticker = await exchange.fetch_ticker(symbol)
        volume_usd = ticker['quoteVolume']
        if volume_usd < 1_000_000:
            logger.info(f"Rejecting {symbol}: Low volume (${volume_usd:.2f} < $1,000,000)")
            return

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

        # Check agreement (75% threshold)
        if analysis_result['agreement'] < 75:
            logger.info(f"Rejecting {symbol}: Low timeframe agreement ({analysis_result['agreement']} < 75%)")
            return

        # Predict signal
        signal = predict_signal(ohlcv_data, indicators, analysis_result)
        if not signal:
            logger.info(f"No signal for {symbol}")
            return

        # Check for duplicate TP/SL values
        if signal['tp1'] == signal['tp2'] == signal['tp3'] == signal['entry']:
            logger.info(f"Rejecting {symbol}: Identical entry and TP values")
            return

        # Check cooldown
        current_time = get_timestamp()
        if symbol in last_signal_time and (current_time - last_signal_time[symbol]) < COOLDOWN:
            logger.info(f"Rejecting {symbol}: In cooldown")
            return

        # Send signal to Telegram
        await send_signal(symbol, signal, TELEGRAM_CHAT_ID)
        last_signal_time[symbol] = current_time
        logger.info(f"Signal sent successfully: {symbol} - {signal['direction']} ✔")

    except Exception as e:
        logger.error(f"Error processing {symbol}: {str(e)}")

async def main():
    """Main loop to process USDT pairs in batches."""
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
    })

    while True:
        try:
            # Fetch USDT pairs
            usdt_pairs = await fetch_usdt_pairs(exchange)

            # Process symbols in batches
            for i in range(0, len(usdt_pairs), BATCH_SIZE):
                batch = usdt_pairs[i:i + BATCH_SIZE]
                tasks = [process_symbol(exchange, symbol) for symbol in batch if symbol not in scanned_symbols]
                await asyncio.gather(*tasks)
                scanned_symbols.update(batch)

            # Clear scanned symbols after full cycle
            if len(scanned_symbols) >= len(usdt_pairs):
                scanned_symbols.clear()
                logger.info("Completed full cycle, resetting scanned symbols")

            # Wait for next cycle (10 minutes)
            await asyncio.sleep(CYCLE_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            await asyncio.sleep(60)

    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
