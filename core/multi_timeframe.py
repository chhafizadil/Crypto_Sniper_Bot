from typing import Dict
from core.indicators import calculate_indicators
from core.candle_patterns import detect_candle_patterns

def multi_timeframe_analysis(indicators: Dict, ohlcv_data: Dict) -> Dict:
    """Perform multi-timeframe analysis for signal agreement."""
    results = {'15m': {}, '1h': {}, '4h': {}, '1d': {}}
    agreement_count = 0
    total_timeframes = len(results)

    for timeframe in results:
        # Get OHLCV data for the timeframe
        ohlcv = ohlcv_data[timeframe]
        # Convert OHLCV to DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calculate indicators using calculate_indicators
        df = calculate_indicators(df)
        
        # Extract latest indicator values
        latest = df.iloc[-1]
        rsi = latest['rsi']
        macd = latest['macd']
        macd_signal = latest['macd_signal']
        vwap = latest['vwap']
        # Detect candle patterns
        candle_patterns = detect_candle_patterns(df)

        # Determine signal direction
        direction = None
        if rsi > 75 and macd > macd_signal:  # Updated RSI threshold
            direction = 'SHORT'
        elif rsi < 25 and macd < macd_signal:  # Updated RSI threshold
            direction = 'LONG'
        elif any(p in ['bullish_engulfing', 'hammer'] for p in candle_patterns):
            direction = 'LONG'
        elif any(p in ['bearish_engulfing', 'shooting_star'] for p in candle_patterns):
            direction = 'SHORT'

        results[timeframe] = {
            'direction': direction,
            'rsi': rsi,
            'macd': {'macd': macd, 'signal': macd_signal},
            'vwap': vwap,
            'candle_patterns': candle_patterns
        }

        if direction:
            agreement_count += 1

    # Calculate agreement percentage
    agreement = (agreement_count / total_timeframes) * 100

    return {
        'agreement': agreement,
        'results': results
    }
