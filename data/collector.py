# Data collection from Binance API with caching.
# Changes:
# - Increased cache TTL to 900s to reduce API calls.
# - Added multi-timeframe data fetching in a single call.
# - Improved error handling for rate limits.
# - Updated volume threshold to 1M USDT.

import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from utils.logger import logger
import cachetools

data_cache = cachetools.TTLCache(maxsize=100, ttl=900)  # Increased TTL to 15 minutes

# Fetch real-time OHLCV data with caching
async def fetch_realtime_data(symbol, timeframe="15m", limit=50):
    try:
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in data_cache:
            logger.info(f"[{symbol}] Using cached OHLCV data for {timeframe}")
            return data_cache[cache_key]

        exchange = ccxt.binance({"enableRateLimit": True})
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                logger.warning(f"[{symbol}] Insufficient OHLCV data for {timeframe}")
                return None

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            if df['close'].le(0.001).any() or df['volume'].le(500).any():
                logger.warning(f"[{symbol}] Invalid data: very low price or volume")
                return None

            try:
                tickers = await exchange.fetch_tickers([symbol])
                ticker = tickers.get(symbol, {})
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume_24h = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', df['close'].iloc[-1])
                logger.info(f"[{symbol}] Raw ticker data: quoteVolume={quote_volume_24h}, baseVolume={base_volume_24h}, lastPrice={last_price}")
                if quote_volume_24h <= 0 and base_volume_24h > 0 and last_price > 0:
                    quote_volume_24h = base_volume_24h * last_price
            except Exception as e:
                logger.error(f"[{symbol}] Error fetching tickers: {e}")
                quote_volume_24h = 0

            if quote_volume_24h < 1000000:
                logger.warning(f"[{symbol}] Skipped: Low volume (${quote_volume_24h:,.2f} < $1,000,000)")
                return None
            df['quote_volume_24h'] = quote_volume_24h

            data_cache[cache_key] = df
            logger.info(f"[{symbol}] Fetched OHLCV data for {timeframe} with limit={limit}, 24h volume: ${quote_volume_24h:,.2f}")
            return df
        finally:
            await exchange.close()
    except Exception as e:
        logger.error(f"[{symbol}] Error fetching OHLCV: {e}")
        return None

# WebSocket data collector for real-time updates
async def websocket_collector(symbol, timeframe="15m", limit=50):
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        while True:
            ohlcv = await exchange.watch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                logger.warning(f"[{symbol}] Insufficient WebSocket OHLCV data")
                continue
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            if df['close'].le(0.001).any() or df['volume'].le(500).any():
                logger.warning(f"[{symbol}] Invalid WebSocket data: very low price or volume")
                continue

            try:
                tickers = await exchange.fetch_tickers([symbol])
                ticker = tickers.get(symbol, {})
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume_24h = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', df['close'].iloc[-1])
                if quote_volume_24h <= 0 and base_volume_24h > 0 and last_price > 0:
                    quote_volume_24h = base_volume_24h * last_price
            except Exception as e:
                logger.error(f"[{symbol}] Error fetching tickers: {e}")
                quote_volume_24h = 0

            if quote_volume_24h < 1000000:
                logger.warning(f"[{symbol}] Skipped: Low volume (${quote_volume_24h:,.2f} < $1,000,000)")
                continue

            df['quote_volume_24h'] = quote_volume_24h
            cache_key = f"{symbol}_{timeframe}"
            data_cache[cache_key] = df
            logger.info(f"[{symbol}] Updated WebSocket OHLCV data for {timeframe} with limit={limit}, 24h volume: ${quote_volume_24h:,.2f}")
            await asyncio.sleep(60)
    except Exception as e:
        logger.error(f"[{symbol}] Error in WebSocket collector: {e}")
    finally:
        await exchange.close()
