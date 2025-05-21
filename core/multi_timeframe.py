import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import logger
import asyncio
import ta

async def fetch_ohlcv(exchange, symbol, timeframe, limit=100):
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

async def multi_timeframe_boost(symbol, exchange, direction):
    try:
        boost = 0
        for timeframe in ['4h', '1d']:
            df = await fetch_ohlcv(exchange, symbol, timeframe)
            if df is None:
                continue

            # Calculate EMAs and volume SMA
            df["ema_20"] = ta.trend.EMAIndicator(df["close"], window=20, fillna=True).ema_indicator()
            df["ema_50"] = ta.trend.EMAIndicator(df["close"], window=50, fillna=True).ema_indicator()
            df["volume_sma_20"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            if len(df) >= 3:
                next_candle = df.iloc[-3]

            # EMA alignment
            if direction == "LONG" and latest["ema_20"] > latest["ema_50"]:
                boost += 5
            elif direction == "SHORT" and latest["ema_20"] < latest["ema_50"]:
                boost += 5
            else:
                logger.warning(f"[{symbol}] {timeframe} EMA misalignment")
                return 0

            # Volume filter
            if latest["volume"] < 1.5 * latest["volume_sma_20"]:
                logger.warning(f"[{symbol}] Low volume on {timeframe}")
                return 0

            # Fake breakout check
            if direction == "LONG" and prev["high"] > latest["high"] and next_candle["close"] <= prev["high"]:
                logger.warning(f"[{symbol}] Fake breakout detected on {timeframe}")
                return 0
            if direction == "SHORT" and prev["low"] < latest["low"] and next_candle["close"] >= prev["low"]:
                logger.warning(f"[{symbol}] Fake breakout detected on {timeframe}")
                return 0

        return boost

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi_timeframe_boost: {e}")
        return 0
