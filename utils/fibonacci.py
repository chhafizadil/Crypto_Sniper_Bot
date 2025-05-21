# Updated utils/fibonacci.py to include only 38.2% and 61.8% levels and improve validation
import pandas as pd
import numpy as np
from utils.logger import logger

def calculate_fibonacci_levels(df):
    try:
        if len(df) < 2 or df['high'].std() <= 0 or df['low'].std() <= 0:
            logger.warning("Insufficient data for Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            fib_levels = {'fib_0.382': 0.0, 'fib_0.618': 0.0}
            for level, value in fib_levels.items():
                dummy_df[level] = value
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        df = df.copy()
        df = df.astype({'high': 'float32', 'low': 'float32', 'close': 'float32'})
        window = min(len(df), 100)
        max_high = df['high'].tail(window).max()
        min_low = df['low'].tail(window).min()

        if pd.isna(max_high) or pd.isna(min_low) or max_high <= min_low:
            logger.warning("Invalid high/low for Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            fib_levels = {'fib_0.382': 0.0, 'fib_0.618': 0.0}
            for level, value in fib_levels.items():
                dummy_df[level] = value
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        diff = max_high - min_low
        fib_levels = {
            'fib_0.382': min_low + 0.382 * diff,
            'fib_0.618': min_low + 0.618 * diff
        }

        for level, value in fib_levels.items():
            df[level] = value

        if df.isna().any().any() or df.isin([np.inf, -np.inf]).any().any():
            logger.warning("NaN or Inf values in Fibonacci levels, returning dummy DataFrame")
            dummy_df = df.copy()
            for level in fib_levels:
                dummy_df[level] = 0.0
            logger.info("Dummy Fibonacci levels added: fib_0.382, fib_0.618")
            return dummy_df

        logger.info(f"Fibonacci levels calculated for {len(df)} rows: fib_0.382, fib_0.618")
        return df
    except Exception as e:
        logger.error(f"Error in calculate_fibonacci_levels: {e}")
        dummy_df = df.copy()
        fib_levels = {'fib_0.382': 0.0, 'fib_0.618': 0.0}
        for level, value in fib_levels.items():
            dummy_df[level] = value
        logger.info("Dummy Fibonacci levels added due to error: fib_0.382, fib_0.618")
        return dummy_df
