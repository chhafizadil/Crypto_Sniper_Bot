import pandas as pd
import numpy as np
from utils.logger import logger

def calculate_fibonacci_levels(df, timeframe="15m"):
    try:
        if len(df) < 2 or df['high'].std() <= 0 or df['low'].std() <= 0:
            logger.warning("Insufficient data for Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            latest_close = dummy_df['close'].iloc[-1] if not dummy_df['close'].empty else 0.0
            fib_levels = {'fib_0.382': latest_close, 'fib_0.618': latest_close}  # Use latest close instead of 0
            for level, value in fib_levels.items():
                dummy_df[level] = value
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        df = df.copy()
        df = df.astype({'high': 'float32', 'low': 'float32', 'close': 'float32'})
        
        # Adjust window size based on timeframe
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
        # Check for small price difference
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
            logger.warning("NaN or Inf values in Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            latest_close = dummy_df['close'].iloc[-1] if not dummy_df['close'].empty else 0.0
            for level in fib_levels:
                dummy_df[level] = latest_close
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        logger.info(f"Fibonacci levels calculated for {len(df)} rows: fib_0.382, fib_0.618")
        return df
    except Exception as e:
        logger.error(f"Error in calculate_fibonacci_levels: {e}")
        dummy_df = df.copy()
        latest_close = dummy_df['close'].iloc[-1] if not dummy_df['close'].empty else 0.0
        fib_levels = {'fib_0.382': latest_close, 'fib_0.618': latest_close}
        for level, value in fib_levels.items():
            dummy_df[level] = value
        logger.info("Dummy Fibonacci levels added due to error: fib_0.382, fib_0.618")
        return dummy_df
