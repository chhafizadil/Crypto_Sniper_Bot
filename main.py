import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from datetime import datetime, timedelta

async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        # Check cooldown from signals.csv
        try:
            signals_df = pd.read_csv('logs/signals.csv')
            symbol_signals = signals_df[signals_df['symbol'] == symbol]
            if not symbol_signals.empty:
                last_signal_time = pd.to_datetime(symbol_signals['timestamp']).max()
                if (datetime.utcnow() - last_signal_time).total_seconds() < 14400:  # 4 hours
                    logger.info(f"[{symbol}] In cooldown, last signal at {last_signal_time}")
                    return None
        except FileNotFoundError:
            logger.warning("signals.csv not found, skipping cooldown check")

        # Analyze each timeframe
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

        # Filter valid signals
        valid_signals = {t: s for t, s in signals.items() if s is not None}
        if not valid_signals:
            logger.info(f"[{symbol}] No valid signals across any timeframe")
            return None

        # Select signal with highest confidence, prefer shorter timeframe if equal
        selected_timeframe = min(valid_signals, key=lambda t: (valid_signals[t]['confidence'] * -1, timeframes.index(t)))
        final_signal = valid_signals[selected_timeframe]
        logger.info(f"[{symbol}] Selected signal from {selected_timeframe} with confidence {final_signal['confidence']:.2f}%")

        # Volume check
        df = await fetch_realtime_data(symbol, selected_timeframe, limit=50)
        if df is None:
            logger.warning(f"[{symbol}] Failed to fetch data for volume check")
            return None

        latest = df.iloc[-1]
        if latest['quote_volume_24h'] < 1000000:  # MIN_VOLUME = 1,000,000
            logger.info(f"[{symbol}] Signal rejected: Quote volume ${latest['quote_volume_24h']:,.2f} < $1,000,000")
            return None

        final_signal['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
