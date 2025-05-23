# Binance API سے ڈیٹا اکٹھا کرنے اور کیشنگ۔
# تبدیلیاں:
# - والیوم تھریش ہولڈ کو $1,000,000 پر سیٹ کیا۔
# - کیش TTL کو 600 سیکنڈ پر اپ ڈیٹ کیا۔
# - API کالز کو آپٹمائز کیا۔

import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from utils.logger import logger
import cachetools

data_cache = cachetools.TTLCache(maxsize=100, ttl=600)

# ریئل ٹائم OHLCV ڈیٹا کیشنگ کے ساتھ
async def fetch_realtime_data(symbol, timeframe="15m", limit=50):
    try:
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in data_cache:
            logger.info(f"[{symbol}] {timeframe} کے لیے کیشڈ OHLCV ڈیٹا استعمال")
            return data_cache[cache_key]

        exchange = ccxt.binance({"enableRateLimit": True})
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                logger.warning(f"[{symbol}] {timeframe} کے لیے ناکافی OHLCV ڈیٹا")
                return None

            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

            if df['close'].le(0.001).any() or df['volume'].le(500).any():
                logger.warning(f"[{symbol}] غلط ڈیٹا: بہت کم قیمت یا والیوم")
                return None

            try:
                tickers = await exchange.fetch_tickers([symbol])
                ticker = tickers.get(symbol, {})
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume_24h = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', df['close'].iloc[-1])
                logger.info(f"[{symbol}] خام ٹکر ڈیٹا: quoteVolume={quote_volume_24h}, baseVolume={base_volume_24h}, lastPrice={last_price}")
                if quote_volume_24h <= 0 and base_volume_24h > 0 and last_price > 0:
                    quote_volume_24h = base_volume_24h * last_price
            except Exception as e:
                logger.error(f"[{symbol}] ٹکرز حاصل کرنے میں خرابی: {e}")
                quote_volume_24h = 0

            if quote_volume_24h < 1000000:
                logger.warning(f"[{symbol}] مسترد: کم والیوم (${quote_volume_24h:,.2f} < $1,000,000)")
                return None
            df['quote_volume_24h'] = quote_volume_24h

            data_cache[cache_key] = df
            logger.info(f"[{symbol}] {timeframe} کے لیے OHLCV ڈیٹا حاصل، limit={limit}, 24h والیوم: ${quote_volume_24h:,.2f}")
            return df
        finally:
            await exchange.close()
    except Exception as e:
        logger.error(f"[{symbol}] OHLCV حاصل کرنے میں خرابی: {e}")
        return None

# WebSocket ڈیٹا کلیکٹر
async def websocket_collector(symbol, timeframe="15m", limit=50):
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        while True:
            ohlcv = await exchange.watch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                logger.warning(f"[{symbol}] ناکافی WebSocket OHLCV ڈیٹا")
                continue
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"], dtype="float32")
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            if df['close'].le(0.001).any() or df['volume'].le(500).any():
                logger.warning(f"[{symbol}] غلط WebSocket ڈیٹا: بہت کم قیمت یا والیوم")
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
                logger.error(f"[{symbol}] ٹکرز حاصل کرنے میں خرابی: {e}")
                quote_volume_24h = 0

            if quote_volume_24h < 1000000:
                logger.warning(f"[{symbol}] مسترد: کم والیوم (${quote_volume_24h:,.2f} < $1,000,000)")
                continue

            df['quote_volume_24h'] = quote_volume_24h
            cache_key = f"{symbol}_{timeframe}"
            data_cache[cache_key] = df
            logger.info(f"[{symbol}] WebSocket OHLCV ڈیٹا اپ ڈیٹ، {timeframe}، limit={limit}, 24h والیوم: ${quote_volume_24h:,.2f}")
            await asyncio.sleep(60)
    except Exception as e:
        logger.error(f"[{symbol}] WebSocket کلیکٹر میں خرابی: {e}")
    finally:
        await exchange.close()
