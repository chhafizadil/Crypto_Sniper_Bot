# Updated core/analysis.py to simplify logging, lower timeframe agreement to 15%, and ensure final signal format
import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger

async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] Fetching OHLCV data for {timeframe}")
                df = await fetch_realtime_data(symbol, timeframe, limit=50)
                if df is None or len(df) < 50:
                    logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                logger.info(f"[{symbol}] OHLCV data fetched for {timeframe}: {len(df)} rows")
                signal = await predictor.predict_signal(symbol, df, timeframe)
                signals[timeframe] = signal
            except Exception as e:
                logger.error(f"[{symbol}] Error analyzing {timeframe}: {str(e)}")
                signals[timeframe] = None
                continue

        valid_signals = [s for s in signals.values() if s is not None]
        if not valid_signals:
            logger.info(f"[{symbol}] No valid signals across any timeframe")
            return signals

        directions = [s['direction'] for s in valid_signals]
        if directions:
            timeframe_agreement = len([d for d in directions if d == directions[0]]) / len(directions)
            logger.info(f"[{symbol}] Timeframe agreement: {timeframe_agreement:.2f}")
            if timeframe_agreement < 0.15:  # Lowered to 15%
                logger.info(f"[{symbol}] Insufficient timeframe agreement ({timeframe_agreement:.2f})")
                return signals
        return signals

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return {}
