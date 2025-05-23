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

        directions = [s['direction'] for s in valid_signals]
        agreement_count = len([d for d in directions if d == directions[0]])
        timeframe_agreement = agreement_count / len(timeframes)
        logger.info(f"[{symbol}] Timeframe agreement: {agreement_count}/{len(timeframes)}")

        if timeframe_agreement < 0.25:  # Reduced from 0.5
            logger.info(f"[{symbol}] Insufficient timeframe agreement ({agreement_count}/{len(timeframes)})")
            return None

        valid_timeframes = [t for t in signals if signals[t] is not None]
        selected_timeframe = '1h' if '1h' in valid_timeframes else valid_timeframes[0]
        final_signal = signals[selected_timeframe]
        if final_signal:
            df = await fetch_realtime_data(symbol, selected_timeframe, limit=50)
            if df is None:
                logger.warning(f"[{symbol}] Failed to fetch data for accuracy check")
                return None

            latest = df.iloc[-1]
            # Relaxed volume check
            if latest['volume'] < 1.2 * latest['volume_sma_20']:  # Reduced from 1.5x
                logger.info(f"[{symbol}] Signal rejected: Volume {latest['volume']:.2f} < 1.2x SMA")
                return None

            if latest['quote_volume_24h'] < 100000:  # Reduced from 500,000
                logger.info(f"[{symbol}] Signal rejected: Quote volume ${latest['quote_volume_24h']:,.2f} < $100,000")
                return None

            final_signal['agreement'] = timeframe_agreement * 100
            logger.info(f"[{symbol}] Selected signal from {selected_timeframe} with agreement {final_signal['agreement']:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
