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
            return None

        directions = [s['direction'] for s in valid_signals]
        agreement_count = len([d for d in directions if d == directions[0]])
        timeframe_agreement = agreement_count / len(timeframes)
        logger.info(f"[{symbol}] Timeframe agreement: {agreement_count}/{len(timeframes)}")

        if agreement_count < 2:  # Require 2/4 timeframe agreement
            logger.info(f"[{symbol}] Insufficient timeframe agreement ({agreement_count}/{len(timeframes)})")
            return None

        # Select signal from 1h timeframe if available, otherwise highest timeframe
        selected_timeframe = '1h' if signals.get('1h') else max([t for t in signals if signals[t]], key=lambda x: timeframes.index(x))
        final_signal = signals[selected_timeframe]
        if final_signal:
            final_signal['agreement'] = timeframe_agreement * 100
            logger.info(f"[{symbol}] Selected signal from {selected_timeframe} with agreement {final_signal['agreement']:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
