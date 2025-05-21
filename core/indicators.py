# Updated core/indicators.py to remove unnecessary indicators, fix MACD with 50 candles, and optimize for soft conditions
import pandas as pd
import numpy as np
import ta
from utils.logger import logger

def calculate_indicators(df):
    try:
        df = df.copy()

        # RSI (softened thresholds)
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14, fillna=True).rsi()

        # Volume SMA 20 (softened threshold)
        df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()

        # MACD (ensure 50 candles for non-zero)
        macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9, fillna=True)
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()

        # ATR (for TP/SL calculation)
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14, fillna=True).average_true_range()

        # ADX (softened threshold)
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14, fillna=True).adx()

        # Handle NaN and Inf
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.ffill(inplace=True)
        df.fillna(0.0, inplace=True)

        logger.info("Indicators calculated: rsi, volume_sma_20, macd, atr, adx")
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return df
