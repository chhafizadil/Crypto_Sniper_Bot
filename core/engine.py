# Adjustments made:
# 1. Increased CYCLE_INTERVAL to 1200 seconds (20 minutes) for slower cycles.
# 2. Added 60-second delay after each batch to reduce signal frequency.
# 3. Limit to 1 signal per batch (highest confidence).
# 4. Increased COOLDOWN to 6 hours (21600 seconds).
# 5. Prevent scanned_symbols reset until cooldown expires.
# 6. Added max 1 signal per minute check.
# 7. Ensured "✔" in logging.

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
logging.basicConfig(level=logging.DEBUG)  # Changed to DEBUG for detailed logs
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
# Last signal sent time for rate limiting
last_signal_sent_time: float = 0
# Minimum interval between signals (60 seconds)
MIN_SIGNAL_INTERVAL = 60

async def fetch_usdt_pairs(exchange: ccxt.binance) -> List[str]:
    """Fetch all USDT trading pairs."""
    markets = await exchange.load_markets()
    usdt_pairs = [symbol for symbol in markets if symbol.endswith('USDT')]
    logger.info(f"Found {len(usdt_pairs)} USDT pairs")
    return usdt_pairs

async def process_symbol(exchange: ccxt.binance, symbol: str) -> Dict:
    """Process a single symbol for signal generation and return signal with confidence."""
    try:
        # Fetch ticker for volume check
        ticker = await exchange.fetch_ticker(symbol)
        volume_usd = ticker['quoteVolume']
        if volume_usd < 2_000_000:  # Updated to 2M USD
            logger.info(f"Rejecting {symbol}: Low volume (${volume_usd:.2f} < $2,000,000)")
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

        # Check agreement (85% threshold)
        if analysis_result['agreement'] < 85:  # Updated to 85%
            logger.info(f"Rejecting {symbol}: Low timeframe agreement ({analysis_result['agreement']} < 85%)")
            return None

        # Predict signal
        signal = predict_signal(ohlcv_data, indicators, analysis_result)
        if not signal:
            logger.info(f"No signal for {symbol}")
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

        return {'signal': signal, 'confidence': signal['confidence'], 'symbol': symbol}

    except Exception as e:
        logger.error(f"Error processing {symbol}: {str(e)}")
        return None

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
                results = await asyncio.gather(*tasks)

                # Select highest confidence signal from batch
                valid_signals = [r for r in results if r is not None]
                if valid_signals:
                    best_signal = max(valid_signals, key=lambda x: x['confidence'])
                    signal = best_signal['signal']
                    symbol = best_signal['symbol']
                    
                    # Check signal rate limit
                    current_time = get_timestamp()
                    if current_time - last_signal_sent_time < MIN_SIGNAL_INTERVAL:
                        logger.info(f"Rate limit: Waiting {MIN_SIGNAL_INTERVAL - (current_time - last_signal_sent_time):.2f} seconds")
                        await asyncio.sleep(MIN_SIGNAL_INTERVAL - (current_time - last_signal_sent_time))
                    
                    # Send signal to Telegram
                    await send_signal(symbol, signal, TELEGRAM_CHAT_ID)
                    last_signal_time[symbol] = current_time
                    last_signal_sent_time = get_timestamp()
                    logger.info(f"Signal sent successfully: {symbol} - {signal['direction']} ✔")
                
                scanned_symbols.update(batch)
                await asyncio.sleep(60)  # 60-second delay after each batch

            # Clear scanned symbols only for symbols past cooldown
            current_time = get_timestamp()
            for symbol in list(scanned_symbols):
                if symbol in last_signal_time and (current_time - last_signal_time[symbol]) >= COOLDOWN:
                    scanned_symbols.remove(symbol)
            logger.info(f"Cycle complete, {len(scanned_symbols)} symbols remain in cooldown")

            # Wait for next cycle (20 minutes)
            await asyncio.sleep(CYCLE_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop error: {str(e)}")
            await asyncio.sleep(60)

    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
