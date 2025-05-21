# Updated data/collector.py to add zero price/volume checks, increase candles to 50, and optimize caching
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from utils.logger import logger
import cachetools

data_cache = cachetools.TTLCache(maxsize=100, ttl=300)  # 5-minute cache

async def fetch_realtime_data(symbol, timeframe="15m", limit=50):
    try:
        if symbol in data_cache:
            logger.info(f"[{symbol}] Using cached OHLCV data")
            return data_cache[symbol]

        exchange = ccxt.binance({"enableRateLimit": True})
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            logger.warning(f"[{symbol}] Insufficient OHLCV data")
            await exchange.close()
            return None

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        # Zero price/volume check
        if df['close'].le(0.01).any() or df['volume'].le(1000).any():
            logger.warning(f"[{symbol}] Invalid data: zero/low price or volume")
            await exchange.close()
            return None
        data_cache[symbol] = df
        logger.info(f"[{symbol}] Fetched OHLCV data for {timeframe} with limit={limit}")
        await exchange.close()
        return df
    except Exception as e:
        logger.error(f"[{symbol}] Error fetching OHLCV: {e}")
        await exchange.close()
        return None

async def websocket_collector(symbol, timeframe="15m", limit=50):
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        while True:
            ohlcv = await exchange.watch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                logger.warning(f"[{symbol}] Insufficient WebSocket OHLCV data")
                continue
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            if df['close'].le(0.01).any() or df['volume'].le(1000).any():
                logger.warning(f"[{symbol}] Invalid WebSocket data: zero/low price or volume")
                continue
            data_cache[symbol] = df
            logger.info(f"[{symbol}] Updated WebSocket OHLCV data for {timeframe} with limit={limit}")
            await asyncio.sleep(60)
    except Exception as e:
        logger.error(f"[{symbol}] Error in WebSocket collector: {e}")
    finally:
        await exchange.close()
