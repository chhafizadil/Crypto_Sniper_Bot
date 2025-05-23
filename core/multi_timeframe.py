# ملٹی ٹائم فریم تجزیہ اور ایگریمنٹ منطق کو ہینڈل کرتا ہے۔
# تبدیلیاں:
# - 2/4 ٹائم فریم ایگریمنٹ نافذ کیا۔
# - والیوم چیک کو $1,000,000 پر اپ ڈیٹ کیا۔
# - غیر جانبدار ایگریمنٹ چیک کے لیے EMA ہٹایا۔

import pandas as pd
import ccxt.async_support as ccxt
from utils.logger import logger
import asyncio
import ta

# مخصوص ٹائم فریم کے لیے OHLCV ڈیٹا حاصل کریں
async def fetch_ohlcv(exchange, symbol, timeframe, limit=50):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            logger.error(f"[{symbol}] {timeframe} کے لیے ناکافی OHLCV ڈیٹا")
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'], dtype='float32')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"[{symbol}] {timeframe} کے لیے OHLCV حاصل کرنے میں ناکامی: {e}")
        return None

# ملٹی ٹائم فریم ایگریمنٹ چیک
async def multi_timeframe_boost(symbol, exchange, direction, timeframes=['15m','1h', '4h', '1d']):
    try:
        signals = []
        for timeframe in timeframes:
            df = await fetch_ohlcv(exchange, symbol, timeframe)
            if df is None:
                continue

            # والیوم SMA
            df["volume_sma_20"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            next_candle = df.iloc[-3] if len(df) >= 3 else None

            # والیوم چیک
            try:
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', 0)
                if quote_volume_24h == 0 and base_volume > 0 and last_price > 0:
                    quote_volume_24h = base_volume * last_price
                if quote_volume_24h < 1000000:
                    logger.warning(f"[{symbol}] {timeframe} پر کم والیوم: ${quote_volume_24h:,.2f} < $1,000,000")
                    continue
            except Exception as e:
                logger.error(f"[{symbol}] والیوم چیک کے لیے ٹکر حاصل کرنے میں خرابی: {str(e)}")
                continue

            # والیوم فلٹر
            if latest["volume"] < 1.2 * latest["volume_sma_20"]:
                logger.warning(f"[{symbol}] {timeframe} پر کم والیوم")
                continue

            # جعلی بریک آؤٹ چیک
            if prev and next_candle:
                if direction == "LONG" and prev["high"] > latest["high"] and next_candle["close"] <= prev["high"]:
                    logger.warning(f"[{symbol}] {timeframe} پر جعلی بریک آؤٹ")
                    continue
                if direction == "SHORT" and prev["low"] < latest["low"] and next_candle["close"] >= prev["low"]:
                    logger.warning(f"[{symbol}] {timeframe} پر جعلی بریک آؤٹ")
                    continue

            signals.append({'timeframe': timeframe, 'direction': direction})

        # 2/4 ٹائم فریم ایگریمنٹ
        agreement_count = len(signals)
        if agreement_count >= 2:
            logger.info(f"[{symbol}] ٹائم فریم ایگریمنٹ: {agreement_count}/{len(timeframes)} for {direction}")
            return signals, agreement_count / len(timeframes) * 100
        else:
            logger.warning(f"[{symbol}] ناکافی ٹائم فریم ایگریمنٹ: {agreement_count}/{len(timeframes)}")
            return [], 0
    except Exception as e:
        logger.error(f"[{symbol}] ملٹی ٹائم فریم بوسٹ میں خرابی: {str(e)}")
        return [], 0
