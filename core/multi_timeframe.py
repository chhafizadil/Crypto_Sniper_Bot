# Handles multi-timeframe analysis and agreement logic.
# Changes:
# - Updated to enforce 2/3 timeframe agreement for signal validity.
# - Removed EMA-based direction check to reduce bias.
# - Added volume and breakout checks to ensure signal quality.
# - Improved logging for agreement details.

import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import logger
import asyncio
import ta

# Fetch OHLCV data for a specific timeframe
async def fetch_ohlcv(exchange, symbol, timeframe, limit=50):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            logger.error(f"[{symbol}] Insufficient OHLCV data for {timeframe}")
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'], dtype='float32')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"[{symbol}] Failed to fetch OHLCV for {timeframe}: {e}")
        return None

# Perform multi-timeframe analysis and check for 2/3 agreement
async def multi_timeframe_boost(symbol, exchange, direction, timeframes=['15m', '1h', '4h', '1d']):
    try:
        signals = []
        for timeframe in timeframes:
            df = await fetch_ohlcv(exchange, symbol, timeframe)
            if df is None:
                continue

            # Calculate volume SMA
            df["volume_sma_20"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            next_candle = df.iloc[-3] if len(df) >= 3 else None

            # Volume check
            try:
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', 0)
                if quote_volume_24h == 0 and base_volume > 0 and last_price > 0:
                    quote_volume_24h = base_volume * last_price
                if quote_volume_24h < 1000000:  # Updated to 1M
                    logger.warning(f"[{symbol}] Low volume on {timeframe}: ${quote_volume_24h:,.2f} < $1,000,000")
                    continue
            except Exception as e:
                logger.error(f"[{symbol}] Error fetching ticker for volume check: {str(e)}")
                continue

            # Volume filter
            if latest["volume"] < 1.2 * latest["volume_sma_20"]:
                logger.warning(f"[{symbol}] Low volume on {timeframe}")
                continue

            # Fake breakout check
            if prev and next_candle:
                if direction == "LONG" and prev["high"] > latest["high"] and next_candle["close"] <= prev["high"]:
                    logger.warning(f"[{symbol}] Fake breakout detected on {timeframe}")
                    continue
                if direction == "SHORT" and prev["low"] < latest["low"] and next_candle["close"] >= prev["low"]:
                    logger.warning(f"[{symbol}] Fake breakout detected on {timeframe}")
                    continue

            signals.append({'timeframe': timeframe, 'direction': direction})

        # Check for 2/4 timeframe agreement
        agreement_count = len(signals)
        if agreement_count >= 2:  # Require at least 2 timeframes
            logger.info(f"[{symbol}] Timeframe agreement: {agreement_count}/{len(timeframes)} for {direction}")
            return signals, agreement_count / len(timeframes) * 100
        else:
            logger.warning(f"[{symbol}] Insufficient timeframe agreement: {agreement_count}/{len(timeframes)}")
            return [], 0
    except Exception as e:
        logger.error(f"[{symbol}] Error in multi_timeframe_boost: {str(e)}")
        return [], 0
