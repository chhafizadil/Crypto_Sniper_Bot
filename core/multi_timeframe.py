# Multi-timeframe agreement logic for signal validation
# Merged from: analysis.py (multi-timeframe agreement logic)
# Changes:
# - Consolidated timeframe agreement check from analysis.py
# - Integrated with indicators.py for indicator calculations
# - Ensured async compatibility with engine.py

import pandas as pd
import asyncio
from core.indicators import calculate_indicators
from data.collector import fetch_realtime_data
from utils.logger import logger

async def check_multi_timeframe_agreement(symbol: str, direction: str, timeframes: list) -> bool:
    # Check if at least 2/4 timeframes agree on signal direction
    try:
        agreement_count = 0
        for timeframe in timeframes:
            # Fetch real-time data for timeframe
            ohlcv = await fetch_realtime_data(symbol, timeframe, limit=100)
            if ohlcv is None or len(ohlcv) < 30:
                logger.warning(f"[{symbol}] Insufficient data for {timeframe}")
                continue

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = calculate_indicators(df)
            latest = df.iloc[-1]

            # Check directional agreement
            is_bullish = (
                latest['rsi'] < 30 or
                (latest['macd'] > latest['macd_signal'] and latest['macd'] > 0) or
                latest['adx'] > 25
            )
            is_bearish = (
                latest['rsi'] > 70 or
                (latest['macd'] < latest['macd_signal'] and latest['macd'] < 0) or
                latest['adx'] > 25
            )

            if direction == "LONG" and is_bullish:
                agreement_count += 1
            elif direction == "SHORT" and is_bearish:
                agreement_count += 1

        # Require at least 2/4 timeframes to agree
        agreement = agreement_count >= 2
        logger.info(f"[{symbol}] Multi-timeframe agreement: {agreement_count}/4 timeframes for {direction}")
        return agreement
    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe agreement: {str(e)}")
        return False
