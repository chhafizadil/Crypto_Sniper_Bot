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
        if not valid_signals:
            logger.info(f"[{symbol}] No valid signals across any timeframe")
            return None

        # Select the strongest signal based on confidence
        final_signal = max(valid_signals, key=lambda x: x['confidence']) if valid_signals else None
        if not final_signal:
            logger.info(f"[{symbol}] No valid signal selected")
            return None

        directions = [s['direction'] for s in valid_signals]
        agreement_count = len([d for d in directions if d == final_signal['direction']])
        timeframe_agreement = agreement_count / len(timeframes)
        logger.info(f"[{symbol}] Timeframe agreement: {agreement_count}/{len(timeframes)}")

        if timeframe_agreement < 0.25:  # Relaxed to 1/4
            logger.info(f"[{symbol}] Insufficient timeframe agreement ({agreement_count}/{len(timeframes)})")
            return None

        final_signal['agreement'] = timeframe_agreement * 100
        logger.info(f"[{symbol}] Selected signal from {final_signal['timeframe']} with agreement {final_signal['agreement']:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
