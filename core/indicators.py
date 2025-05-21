import pandas as pd
import numpy as np
import ta
from utils.logger import logger

def calculate_indicators(df):
    try:
        df = df.copy()

        # RSI (corrected thresholds)
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14, fillna=True).rsi()

        # Volume SMA 20
        df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()

        # MACD (fixed for non-zero)
        macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()

        # ATR (for TP/SL)
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14, fillna=True).average_true_range()

        # ADX
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14, fillna=True).adx()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2, fillna=True)
        df['bollinger_upper'] = bb.bollinger_hband()
        df['bollinger_lower'] = bb.bollinger_lband()

        # Stochastic Oscillator
        stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3, fillna=True)
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()

        # VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        # Handle NaN and Inf
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.ffill(inplace=True)
        df.fillna(0.0, inplace=True)

        logger.info("Indicators calculated: rsi, volume_sma_20, macd, atr, adx, bollinger_bands, stochastic, vwap")
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return df
