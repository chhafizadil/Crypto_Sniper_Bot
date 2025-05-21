import pandas as pd
import numpy as np
from utils.logger import logger

def calculate_support_resistance(symbol: str, df: pd.DataFrame) -> dict:
    try:
        window = min(len(df), 100)
        recent_df = df.tail(window).copy()
        
        if len(recent_df) < 20:
            logger.warning(f"[{symbol}] Insufficient data for support/resistance")
            latest_close = recent_df['close'].iloc[-1] if not recent_df['close'].empty else 0.0
            return {'support': latest_close * 0.98, 'resistance': latest_close * 1.02}  # Use close ±2%
            
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
            
        # Ensure minimum distance between support and resistance
        min_distance = 0.02 * latest_close  # At least 2% of current price
        if abs(resistance - support) < min_distance:
            logger.warning(f"[{symbol}] Support and resistance too close: support={support}, resistance={resistance}")
            support = latest_close * 0.98
            resistance = latest_close * 1.02
            
        # Validate non-zero and reasonable support/resistance
        if support <= 0.001 or resistance <= 0.001 or support >= resistance:
            logger.warning(f"[{symbol}] Invalid support/resistance: support={support}, resistance={resistance}")
            return {'support': latest_close * 0.98, 'resistance': latest_close * 1.02}
            
        logger.info(f"[{symbol}] Support: {support}, Resistance: {resistance}")
        return {'support': support, 'resistance': resistance}
    except Exception as e:
        logger.error(f"[{symbol}] Error calculating support/resistance: {str(e)}")
        latest_close = df['close'].iloc[-1] if not df['close'].empty else 0.0
        return {'support': latest_close * 0.98, 'resistance': latest_close * 1.02}
