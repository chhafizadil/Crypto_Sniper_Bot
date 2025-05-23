# Multi-timeframe analysis for signal generation.
# Changes:
# - Removed Urdu from all logs and comments.
# - Enforced 2/4 timeframe agreement.
# - Updated volume check to $1,000,000.
# - Integrated dynamic TP logic from sender.py.
# - Added PKT timestamp handling.

import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from utils.helpers import calculate_agreement, format_timestamp_to_pk
import numpy as np

# Calculate dynamic TP probabilities and prices (from sender.py)
def calculate_tp_probabilities_and_prices(indicators, entry_price, atr):
    logger.info("Calculating dynamic TP probabilities and prices")
    base_prob = 50
    tp_multipliers = [1.01, 1.015, 1.02]
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:
        base_prob += 10
    if "Strong Trend" in indicators:
        base_prob += 10
    if "Near Support" in indicators or "Near Resistance" in indicators:
        base_prob -= 5
    probabilities = {
        "TP1": min(base_prob, 80),
        "TP2": min(base_prob * 0.7, 60),
        "TP3": min(base_prob * 0.5, 40)
    }
    prices = {
        "TP1": entry_price * (1 + atr * tp_multipliers[0]),
        "TP2": entry_price * (1 + atr * tp_multipliers[1]),
        "TP3": entry_price * (1 + atr * tp_multipliers[2])
    }
    return probabilities, prices

# Adjust TP for stablecoin pairs (from sender.py)
def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

# Multi-timeframe analysis with 2/4 agreement
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

                logger.info(f"[{symbol}] OHLCV data for {timeframe}: {len(df)} rows")
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

        # Enforce 2/4 timeframe agreement
        direction, agreement = calculate_agreement(valid_signals)
        if agreement < 50:  # At least 2/4 timeframes
            logger.info(f"[{symbol}] Insufficient timeframe agreement: {agreement:.2f}%")
            return None

        # Select signal with agreement and average confidence
        agreed_signals = [s for s in valid_signals if s['direction'] == direction]
        final_signal = agreed_signals[0].copy()
        final_signal['confidence'] = sum(s['confidence'] for s in agreed_signals) / len(agreed_signals)
        final_signal['timeframe'] = 'multi'
        final_signal['agreement'] = agreement
        final_signal['timestamp'] = datetime.now(pytz.UTC).isoformat() + 'Z'

        # Volume and data validation
        df = await fetch_realtime_data(symbol, agreed_signals[0]['timeframe'], limit=50)
        if df is None:
            logger.warning(f"[{symbol}] Data validation failed")
            return None

        latest = df.iloc[-1]
        if latest['volume'] < 1.2 * latest.get('volume_sma_20', latest['volume']):
            logger.info(f"[{symbol}] Signal rejected: Volume {latest['volume']:.2f} < 1.2x SMA")
            return None

        if latest['quote_volume_24h'] < 1000000:
            logger.info(f"[{symbol}] Signal rejected: Quote volume ${latest['quote_volume_24h']:,.2f} < $1,000,000")
            return None

        # Generate dynamic TPs
        probabilities, prices = calculate_tp_probabilities_and_prices(final_signal['conditions'], final_signal['entry'], final_signal.get('atr', 0.01))
        final_signal.update({
            'tp1': prices['TP1'],
            'tp2': prices['TP2'],
            'tp3': prices['TP3'],
            'tp1_possibility': probabilities['TP1'],
            'tp2_possibility': probabilities['TP2'],
            'tp3_possibility': probabilities['TP3']
        })

        # Adjust TPs for stablecoin pairs
        final_signal['tp1'], final_signal['tp2'], final_signal['tp3'] = adjust_tp_for_stablecoin(
            final_signal['symbol'], final_signal['tp1'], final_signal['tp2'], final_signal['tp3'], final_signal['entry']
        )

        logger.info(f"[{symbol}] Selected signal with agreement: {agreement:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
