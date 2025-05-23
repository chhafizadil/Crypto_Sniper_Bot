# Multi-timeframe analysis for signal generation.
# Changes:
# - Implemented 2/3 timeframe agreement logic.
# - Removed biased timeframe selection (e.g., preferring 1h).
# - Added neutral signal generation to avoid LONG/SHORT bias.
# - Improved volume and data validation.

import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from utils.helpers import calculate_agreement

# Analyze symbol across multiple timeframes with 2/3 agreement
async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] Fetching OHLCV data for {timeframe}")
                df = await fetch_realtime_data(symbol, timeframe, limit=50)
                if df is None or len(df) < 30:
                    logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                logger.info(f"[{symbol}] OHLCV data fetched for {timeframe}: {len(df)} rows")
                signal = await predictor.predict_signal(symbol, df, timeframe)
                signals[timeframe] = signal
                logger.info(f"[{symbol}] Signal for {timeframe}: {signal}")
            except Exception as e:
                logger.error(f"[{symbol}] Error analyzing {timeframe}: {str(e)}")
                signals[timeframe] = None
                continue

        valid_signals = [s for s in signals.values() if s is not None]
        if len(valid_signals) < 2:
            logger.info(f"[{symbol}] Insufficient valid signals: {len(valid_signals)}/{len(timeframes)}")
            return None

        # Check for 2/3 timeframe agreement
        direction, agreement = calculate_agreement(valid_signals)
        if agreement < 50:  # At least 2/4 timeframes (50%)
            logger.info(f"[{symbol}] Insufficient timeframe agreement: {agreement:.2f}%")
            return None

        # Select signals with agreed direction and average confidence
        agreed_signals = [s for s in valid_signals if s['direction'] == direction]
        final_signal = agreed_signals[0].copy()
        final_signal['confidence'] = sum(s['confidence'] for s in agreed_signals) / len(agreed_signals)
        final_signal['timeframe'] = 'multi'
        final_signal['agreement'] = agreement

        # Volume and data validation
        df = await fetch_realtime_data(symbol, agreed_signals[0]['timeframe'], limit=50)
        if df is None:
            logger.warning(f"[{symbol}] Failed to fetch data for validation")
            return None

        latest = df.iloc[-1]
        if latest['volume'] < 1.2 * latest.get('volume_sma_20', latest['volume']):
            logger.info(f"[{symbol}] Signal rejected: Volume {latest['volume']:.2f} < 1.2x SMA")
            return None

        if latest['quote_volume_24h'] < 1000000:
            logger.info(f"[{symbol}] Signal rejected: Quote volume ${latest['quote_volume_24h']:,.2f} < $1,000,000")
            return None

        logger.info(f"[{symbol}] Selected signal with agreement {agreement:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
