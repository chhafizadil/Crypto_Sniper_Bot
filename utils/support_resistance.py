# Updated utils/support_resistance.py to increase range to 10% and improve validation
import pandas as pd
import numpy as np
from utils.logger import logger

def calculate_support_resistance(symbol: str, df: pd.DataFrame) -> dict:
    try:
        window = min(len(df), 100)
        recent_df = df.tail(window).copy()
        
        if len(recent_df) < 20:
            logger.warning(f"[{symbol}] Insufficient data for support/resistance")
            return {'support': 0.0, 'resistance': 0.0}
            
        pivots_high = recent_df['high'].rolling(window=5, center=True).max()
        pivots_low = recent_df['low'].rolling(window=5, center=True).min()
        
        resistance_levels = recent_df[pivots_high == recent_df['high']]['high'].dropna()
        support_levels = recent_df[pivots_low == recent_df['low']]['low'].dropna()
        
        if len(resistance_levels) > 0:
            resistance = float(np.mean(resistance_levels))
        else:
            resistance = float(recent_df['high'].max())
            
        if len(support_levels) > 0:
            support = float(np.mean(support_levels))
        else:
            support = float(recent_df['low'].min())
            
        # Validate non-zero support/resistance
        if support <= 0.01 or resistance <= 0.01:
            logger.warning(f"[{symbol}] Invalid support/resistance: support={support}, resistance={resistance}")
            return {'support': 0.0, 'resistance': 0.0}
            
        logger.info(f"[{symbol}] Support: {support}, Resistance: {resistance}")
        return {'support': support, 'resistance': resistance}
    except Exception as e:
        logger.error(f"[{symbol}] Error calculating support/resistance: {str(e)}")
        return {'support': 0.0, 'resistance': 0.0}
