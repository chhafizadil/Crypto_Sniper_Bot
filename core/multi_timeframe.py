import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import logger
import asyncio
import ta

async def fetch_ohlcv(exchange, symbol, timeframe, limit=50):  # Reduced limit
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

async def multi_timeframe_boost(symbol, exchange, direction, timeframes=['15m','1h', '4h', '1d']):
    try:
        signals = []
        for timeframe in timeframes:
            df = await fetch_ohlcv(exchange, symbol, timeframe)
            if df is None:
                continue

            # Calculate EMAs and volume SMA
            df["ema_20"] = ta.trend.EMAIndicator(df["close"], window=20, fillna=True).ema_indicator()
            df["ema_50"] = ta.trend.EMAIndicator(df["close"], window=50, fillna=True).ema_indicator()
            df["volume_sma_20"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            next_candle = df.iloc[-3] if len(df) >= 3 else None

            # EMA alignment
            timeframe_direction = None
            if direction == "LONG" and latest["ema_20"] > latest["ema_50"]:
                timeframe_direction = "LONG"
            elif direction == "SHORT" and latest["ema_20"] < latest["ema_50"]:
                timeframe_direction = "SHORT"

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

            if timeframe_direction == direction:
                signals.append({'timeframe': timeframe, 'direction': direction})

        # Check for 2/4 timeframe agreement
        agreement_count = len(signals)
        if agreement_count >= 3:  # Keep 2/4 agreement
            logger.info(f"[{symbol}] Timeframe agreement: {agreement_count}/{len(timeframes)} for {direction}")
            return signals, agreement_count / len(timeframes) * 100
        else:
            logger.warning(f"[{symbol}] Insufficient timeframe agreement: {agreement_count}/{len(timeframes)}")
            return [], 0
    except Exception as e:
        logger.error(f"[{symbol}] Error in multi_timeframe_boost: {str(e)}")
        return [], 0
