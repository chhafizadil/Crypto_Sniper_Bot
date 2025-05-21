import pandas as pd
import numpy as np
import ta
from utils.logger import logger

def calculate_indicators(df):
    try:
        df = df.copy()

        # Validate input data
        if len(df) < 50 or df[['open', 'high', 'low', 'close', 'volume']].isnull().any().any():
            logger.warning("Invalid or insufficient input data for indicators")
            return df

        logger.info(f"Calculating indicators for {len(df)} candles")

        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14, fillna=False).rsi()

        # Volume SMA 20
        df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()

        # MACD (improved to avoid zero values)
        macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9, fillna=False)
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        # Manual check for zero MACD
        if df['macd'].abs().mean() < 1e-5:
            logger.warning("MACD values near zero, recalculating with scaled close prices")
            scaled_close = df['close'] * 1000  # Scale to avoid precision issues
            macd = ta.trend.MACD(scaled_close, window_slow=26, window_fast=12, window_sign=9, fillna=False)
            df['macd'] = macd.macd() / 1000
            df['macd_signal'] = macd.macd_signal() / 1000

        # ATR
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14, fillna=False).average_true_range()

        # ADX
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14, fillna=False).adx()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2, fillna=False)
        df['bollinger_upper'] = bb.bollinger_hband()
        df['bollinger_lower'] = bb.bollinger_lband()

        # Stochastic Oscillator
        stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3, fillna=False)
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()

        # VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

        # Handle NaN and Inf
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.ffill(inplace=True)
        df.fillna(df.mean(numeric_only=True), inplace=True)  # Use mean instead of 0 to avoid zeroing out indicators

        logger.info("Indicators calculated: rsi, volume_sma_20, macd, atr, adx, bollinger_bands, stochastic, vwap")
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return df
