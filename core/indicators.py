# Technical indicators and analysis for signal generation
# Merged from analysis.py, candle_patterns.py, fibonacci.py, support_resistance.py
# Changes:
# - Consolidated TP calculations from analysis.py
# - Integrated candle patterns from candle_patterns.py
# - Added Fibonacci and support/resistance calculations
# - Ensured compatibility with predictor.py and multi_timeframe.py

import pandas as pd
import numpy as np
from utils.logger import logger
from datetime import datetime
import pytz

# Calculate EMA manually to avoid library issues
def calculate_ema(series, period):
    # Calculate exponential moving average
    return series.ewm(span=period, adjust=False).mean()

# Calculate technical indicators (RSI, MACD, ATR, etc.)
def calculate_indicators(df):
    try:
        df = df.copy()
        # Validate input data
        if len(df) < 30 or df[['open', 'high', 'low', 'close', 'volume']].isnull().any().any():
            logger.warning("Invalid or insufficient input data for indicators")
            return df

        logger.info(f"Calculating indicators for {len(df)} candles")

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Volume SMA 20
        df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()

        # MACD
        scaled_close = df['close'] * 1000
        ema_fast = calculate_ema(scaled_close, 12)
        ema_slow = calculate_ema(scaled_close, 26)
        df['macd'] = (ema_fast - ema_slow) / 1000
        df['macd_signal'] = calculate_ema(df['macd'], 9)
        if df['macd'].abs().mean() < 1e-5:
            logger.warning("MACD values near zero, possible data issue")

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()

        # ADX
        plus_dm = df['high'].diff().where(df['high'].diff() > df['low'].diff(), 0)
        minus_dm = (-df['low'].diff()).where(df['low'].diff() < df['high'].diff(), 0)
        tr = tr.rolling(window=14).sum()
        plus_di = 100 * (plus_dm.rolling(window=14).sum() / tr)
        minus_di = 100 * (minus_dm.rolling(window=14).sum() / tr)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        df['adx'] = np.clip(dx.rolling(window=14).mean(), 0, 100)

        # Bollinger Bands
        sma_20 = df['close'].rolling(window=20).mean()
        std_20 = df['close'].rolling(window=20).std()
        df['bollinger_upper'] = sma_20 + 2 * std_20
        df['bollinger_lower'] = sma_20 - 2 * std_20

        # Stochastic Oscillator
        lowest_low = df['low'].rolling(window=14).min()
        highest_high = df['high'].rolling(window=14).max()
        df['stoch_k'] = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()

        # VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        # Handle NaN and Inf
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.ffill(inplace=True)
        df.fillna(df.mean(numeric_only=True), inplace=True)

        logger.info("Indicators calculated: rsi, volume_sma_20, macd, atr, adx, bollinger_bands, stochastic, vwap")
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return df

# Calculate dynamic TP probabilities and prices (from analysis.py)
def calculate_tp_probabilities_and_prices(indicators, entry_price, atr):
    # Calculate TP probabilities based on indicators
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

# Adjust TP for stablecoin pairs (from analysis.py)
def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    # Adjust TP levels for USDT pairs
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

# Candle pattern detection (from candle_patterns.py)
def is_bullish_engulfing(df):
    try:
        if len(df) < 2:
            logger.warning("Insufficient data for bullish engulfing")
            return [False] * len(df)
        prev_candle = df.shift(1)
        conditions = (
            (prev_candle['close'] < prev_candle['open']) &
            (df['close'] > df['open']) &
            (df['open'] <= prev_candle['close']) &
            (df['close'] >= prev_candle['open'])
        )
        logger.info("Bullish engulfing pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_bullish_engulfing: {str(e)}")
        return [False] * len(df)

def is_bearish_engulfing(df):
    try:
        if len(df) < 2:
            logger.warning("Insufficient data for bearish engulfing")
            return [False] * len(df)
        prev_candle = df.shift(1)
        conditions = (
            (prev_candle['close'] > prev_candle['open']) &
            (df['close'] < df['open']) &
            (df['open'] >= prev_candle['close']) &
            (df['close'] <= prev_candle['open'])
        )
        logger.info("Bearish engulfing pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_bearish_engulfing: {str(e)}")
        return [False] * len(df)

def is_doji(df):
    try:
        body = abs(df['close'] - df['open'])
        range_candle = df['high'] - df['low']
        conditions = (body <= range_candle * 0.1) & (range_candle > 0)
        logger.info("Doji pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_doji: {str(e)}")
        return [False] * len(df)

def is_hammer(df):
    try:
        body = abs(df['close'] - df['open'])
        lower_shadow = df['open'].where(df['close'] >= df['open'], df['close']) - df['low']
        upper_shadow = df['high'] - df['close'].where(df['close'] >= df['open'], df['open'])
        range_candle = df['high'] - df['low']
        conditions = (
            (lower_shadow >= 2 * body) &
            (upper_shadow <= body * 0.5) &
            (range_candle > 0)
        )
        logger.info("Hammer pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_hammer: {str(e)}")
        return [False] * len(df)

def is_shooting_star(df):
    try:
        body = abs(df['close'] - df['open'])
        upper_shadow = df['high'] - df['close'].where(df['close'] >= df['open'], df['open'])
        lower_shadow = df['open'].where(df['close'] >= df['open'], df['close']) - df['low']
        range_candle = df['high'] - df['low']
        conditions = (
            (upper_shadow >= 2 * body) &
            (lower_shadow <= body * 0.5) &
            (range_candle > 0)
        )
        logger.info("Shooting star pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_shooting_star: {str(e)}")
        return [False] * len(df)

def is_three_white_soldiers(df):
    try:
        if len(df) < 3:
            logger.warning("Insufficient data for three white soldiers")
            return [False] * len(df)
        candle_1 = df.shift(2)
        candle_2 = df.shift(1)
        avg_volume = df['volume'].rolling(window=20).mean()
        min_candle_size = (df['high'] - df['low']).mean() * 0.5
        conditions = (
            (candle_1['close'] > candle_1['open']) &
            (candle_2['close'] > candle_2['open']) &
            (df['close'] > df['open']) &
            (candle_2['close'] > candle_1['close']) &
            (df['close'] > candle_2['close']) &
            (candle_2['open'] > candle_1['open']) &
            (df['open'] > candle_2['open']) &
            (df['volume'] > avg_volume) &
            ((df['close'] - df['open']) > min_candle_size)
        )
        logger.info("Three white soldiers pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_three_white_soldiers: {str(e)}")
        return [False] * len(df)

def is_three_black_crows(df):
    try:
        if len(df) < 3:
            logger.warning("Insufficient data for three black crows")
            return [False] * len(df)
        candle_1 = df.shift(2)
        candle_2 = df.shift(1)
        avg_volume = df['volume'].rolling(window=20).mean()
        min_candle_size = (df['high'] - df['low']).mean() * 0.5
        conditions = (
            (candle_1['close'] < candle_1['open']) &
            (candle_2['close'] < candle_2['open']) &
            (df['close'] < df['open']) &
            (candle_2['close'] < candle_1['close']) &
            (df['close'] < candle_2['close']) &
            (candle_2['open'] < candle_1['open']) &
            (df['open'] < candle_2['open']) &
            (df['volume'] > avg_volume) &
            ((df['open'] - df['close']) > min_candle_size)
        )
        logger.info("Three black crows pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_three_black_crows: {str(e)}")
        return [False] * len(df)

# Detect all candle patterns
def detect_candle_patterns(df: pd.DataFrame) -> list:
    # Detect candle patterns and return list
    try:
        patterns = []
        if is_bullish_engulfing(df).iloc[-1]:
            patterns.append('bullish_engulfing')
        if is_bearish_engulfing(df).iloc[-1]:
            patterns.append('bearish_engulfing')
        if is_doji(df).iloc[-1]:
            patterns.append('doji')
        if is_hammer(df).iloc[-1]:
            patterns.append('hammer')
        if is_shooting_star(df).iloc[-1]:
            patterns.append('shooting_star')
        if is_three_white_soldiers(df).iloc[-1]:
            patterns.append('three_white_soldiers')
        if is_three_black_crows(df).iloc[-1]:
            patterns.append('three_black_crows')
        logger.info(f"Candle patterns detected: {patterns if patterns else 'None'}")
        return patterns
    except Exception as e:
        logger.error(f"Error in detect_candle_patterns: {str(e)}")
        return []

# Calculate Fibonacci levels (from fibonacci.py)
def calculate_fibonacci_levels(df, timeframe="15m"):
    # Calculate Fibonacci retracement levels
    try:
        if len(df) < 2 or df['high'].std() <= 0 or df['low'].std() <= 0:
            logger.warning("Insufficient data for Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            latest_close = dummy_df['close'].iloc[-1] if not dummy_df['close'].empty else 0.0
            fib_levels = {'fib_0.382': latest_close, 'fib_0.618': latest_close}
            for level, value in fib_levels.items():
                dummy_df[level] = value
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        df = df.copy()
        df = df.astype({'high': 'float32', 'low': 'float32', 'close': 'float32'})
        window_map = {'15m': 100, '1h': 50, '4h': 30, '1d': 20}
        window = min(len(df), window_map.get(timeframe, 100))
        max_high = df['high'].tail(window).max()
        min_low = df['low'].tail(window).min()

        if pd.isna(max_high) or pd.isna(min_low) or max_high <= min_low:
            logger.warning("Invalid high/low for Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            latest_close = dummy_df['close'].iloc[-1] if not dummy_df['close'].empty else 0.0
            fib_levels = {'fib_0.382': latest_close, 'fib_0.618': latest_close}
            for level, value in fib_levels.items():
                dummy_df[level] = value
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        diff = max_high - min_low
        if diff < 0.01 * min_low:
            logger.warning("Price range too small for meaningful Fibonacci levels, using latest close")
            latest_close = df['close'].iloc[-1]
            fib_levels = {'fib_0.382': latest_close, 'fib_0.618': latest_close}
        else:
            fib_levels = {
                'fib_0.382': min_low + 0.382 * diff,
                'fib_0.618': min_low + 0.618 * diff
            }

        for level, value in fib_levels.items():
            df[level] = value

        if df.isna().any().any() or df.isin([np.inf, -np.inf]).any().any():
            logger.error(f"NaN or Inf values detected in Fibonacci levels")
            return df

        logger.info(f"Fibonacci levels calculated for {len(df)} rows: fib_0.382, fib_0.618")
        return df
    except Exception as e:
        logger.error(f"Error in calculate_fibonacci_levels: {e}")
        return df

# Calculate support and resistance levels (from support_resistance.py)
def calculate_support_resistance(symbol: str, df: pd.DataFrame) -> dict:
    # Calculate support and resistance levels based on recent price action
    try:
        window = min(len(df), 100)
        recent_df = df.tail(window).copy()
        
        if len(recent_df) < 20:
            logger.warning(f"[{symbol}] Insufficient data for support/resistance")
            latest_close = recent_df['close'].iloc[-1] if not recent_df['close'].empty else 0.0
            return {'support': latest_close * 0.99, 'resistance': latest_close * 1.01}

        pivots_high = recent_df['high'].rolling(window=5, center=True).max()
        pivots_low = recent_df['low'].rolling(window=5, center=True).min()
        
        resistance_levels = recent_df[pivots_high == recent_df['high']]['high'].dropna()
        support_levels = recent_df[pivots_low == recent_df['low']]['low'].dropna()
        
        latest_close = recent_df['close'].iloc[-1]
        if len(resistance_levels) > 0:
            resistance = float(np.mean(resistance_levels))
        else:
            resistance = float(recent_df['high'].max())
            
        if len(support_levels) > 0:
            support = float(np.mean(support_levels))
        else:
            support = float(recent_df['low'].min())
            
        min_distance = 0.002 * latest_close
        if abs(resistance - support) < min_distance:
            logger.warning(f"[{symbol}] Support and resistance too close: support={support}, resistance={resistance}")
            support = latest_close * 0.99
            resistance = latest_close * 1.01
            
        if support <= 0.001 or resistance <= 0.001 or support >= resistance:
            logger.warning(f"[{symbol}] Invalid support/resistance: support={support}, resistance={resistance}")
            return {'support': latest_close * 0.99, 'resistance': latest_close * 1.01}
            
        logger.info(f"[{symbol}] Support: {support}, Resistance: {resistance}")
        return {'support': support, 'resistance': resistance}
    except Exception as e:
        logger.error(f"[{symbol}] Error calculating support/resistance: {str(e)}")
        latest_close = df['close'].iloc[-1] if not df['close'].empty else 0.0
        return {'support': latest_close * 0.99, 'resistance': latest_close * 1.01}
