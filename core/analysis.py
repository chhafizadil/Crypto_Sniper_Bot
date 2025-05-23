# سگنل جنریشن کے لیے ملٹی ٹائم فریم تجزیہ۔
# تبدیلیاں:
# - 2/4 ٹائم فریم ایگریمنٹ نافذ کیا۔
# - والیوم چیک کو $1,000,000 پر اپ ڈیٹ کیا۔
# - غیر جانبدار سگنل جنریشن۔

import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from utils.helpers import calculate_agreement

# ملٹی ٹائم فریم تجزیہ 2/4 ایگریمنٹ کے ساتھ
async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] {timeframe} کے لیے OHLCV ڈیٹا حاصل")
                df = await fetch_realtime_data(symbol, timeframe, limit=50)
                if df is None or len(df) < 30:
                    logger.warning(f"[{symbol}] ناکافی ڈیٹا {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                logger.info(f"[{symbol}] {timeframe} کے لیے OHLCV ڈیٹا: {len(df)} قطاریں")
                signal = await predictor.predict_signal(symbol, df, timeframe)
                signals[timeframe] = signal
                logger.info(f"[{symbol}] {timeframe} کے لیے سگنل: {signal}")
            except Exception as e:
                logger.error(f"[{symbol}] {timeframe} تجزیہ میں خرابی: {str(e)}")
                signals[timeframe] = None
                continue

        valid_signals = [s for s in signals.values() if s is not None]
        if len(valid_signals) < 2:
            logger.info(f"[{symbol}] ناکافی درست سگنلز: {len(valid_signals)}/{len(timeframes)}")
            return None

        # 2/4 ٹائم فریم ایگریمنٹ
        direction, agreement = calculate_agreement(valid_signals)
        if agreement < 50:  # کم از کم 2/4 ٹائم فریمز
            logger.info(f"[{symbol}] ناکافی ٹائم فریم ایگریمنٹ: {agreement:.2f}%")
            return None

        # اتفاق والے سگنلز اور اوسط اعتماد
        agreed_signals = [s for s in valid_signals if s['direction'] == direction]
        final_signal = agreed_signals[0].copy()
        final_signal['confidence'] = sum(s['confidence'] for s in agreed_signals) / len(agreed_signals)
        final_signal['timeframe'] = 'multi'
        final_signal['agreement'] = agreement

        # والیوم اور ڈیٹا تصدیق
        df = await fetch_realtime_data(symbol, agreed_signals[0]['timeframe'], limit=50)
        if df is None:
            logger.warning(f"[{symbol}] تصدیق کے لیے ڈیٹا ناکام")
            return None

        latest = df.iloc[-1]
        if latest['volume'] < 1.2 * latest.get('volume_sma_20', latest['volume']):
            logger.info(f"[{symbol}] سگنل مسترد: والیوم {latest['volume']:.2f} < 1.2x SMA")
            return None

        if latest['quote_volume_24h'] < 1000000:
            logger.info(f"[{symbol}] سگنل مسترد: کوٹ والیوم ${latest['quote_volume_24h']:,.2f} < $1,000,000")
            return None

        logger.info(f"[{symbol}] ایگریمنٹ کے ساتھ سگنل منتخب: {agreement:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] ملٹی ٹائم فریم تجزیہ میں خرابی: {str(e)}")
        return None
