import pandas as pd
import numpy as np
from utils.logger import logger

def calculate_ema(series, period):
    """Manual EMA calculation to avoid library issues"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_indicators(df):
    try:
        df = df.copy()

        # Validate input data
        if len(df) < 30 or df[['open', 'high', 'low', 'close', 'volume']].isnull().any().any():
            logger.warning("Invalid or insufficient input data for indicators")
            return df

        logger.info(f"Calculating indicators for {len(df)} candles")

        # RSI with null handling
        try:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).fillna(0)
            loss = -delta.where(delta < 0, 0).fillna(0)
            gain_avg = gain.rolling(window=14, min_periods=1).mean()
            loss_avg = loss.rolling(window=14, min_periods=1).mean()
            rs = gain_avg / loss_avg
            df['rsi'] = 100 - (100 / (1 + rs))
            df['rsi'] = df['rsi'].fillna(50)  # Default to neutral RSI
        except Exception as e:
            logger.error(f"Error calculating RSI: {str(e)}")
            df['rsi'] = 50  # Fallback to neutral

        # Volume SMA 20
        df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()

        # MACD
        scaled_close = df['close'] * 1000
        ema_fast = calculate_ema(scaled_close, 12)
        ema_slow = calculate_ema(scaled_close, 26)
        df['macd'] = (ema_fast - ema_slow) / 1000
        df['macd_signal'] = calculate_ema(df['macd'], 9)
        df['macd'] = df['macd'].fillna(0)
        df['macd_signal'] = df['macd_signal'].fillna(0)

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14, min_periods=1).mean().fillna(0)

        # ADX
        plus_dm = df['high'].diff().where(df['high'].diff() > df['low'].diff(), 0)
        minus_dm = (-df['low'].diff()).where(df['low'].diff() < df['high'].diff(), 0)
        tr = tr.rolling(window=14, min_periods=1).sum()
        plus_di = 100 * (plus_dm.rolling(window=14, min_periods=1).sum() / tr)
        minus_di = 100 * (minus_dm.rolling(window=14, min_periods=1).sum() / tr)
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        df['adx'] = np.clip(dx.rolling(window=14, min_periods=1).mean(), 0, 100).fillna(25)

        # Bollinger Bands
        sma_20 = df['close'].rolling(window=20, min_periods=1).mean()
        std_20 = df['close'].rolling(window=20, min_periods=1).std()
        df['bollinger_upper'] = sma_20 + 2 * std_20
        df['bollinger_lower'] = sma_20 - 2 * std_20
        df['bollinger_upper'] = df['bollinger_upper'].fillna(sma_20)
        df['bollinger_lower'] = df['bollinger_lower'].fillna(sma_20)

        # Stochastic Oscillator
        lowest_low = df['low'].rolling(window=14, min_periods=1).min()
        highest_high = df['high'].rolling(window=14, min_periods=1).max()
        df['stoch_k'] = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
        df['stoch_d'] = df['stoch_k'].rolling(window=3, min_periods=1).mean()
        df['stoch_k'] = df['stoch_k'].fillna(50)
        df['stoch_d'] = df['stoch_d'].fillna(50)

        # VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
        df['vwap'] = df['vwap'].fillna(df['close'])

        # Handle NaN and Inf
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.ffill(inplace=True)
        df.fillna(df.mean(numeric_only=True), inplace=True)

        logger.info("Indicators calculated: rsi, volume_sma_20, macd, atr, adx, bollinger_bands, stochastic, vwap")
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        return df
