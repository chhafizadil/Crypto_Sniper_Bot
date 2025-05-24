from typing import Dict
from core.indicators import calculate_rsi, calculate_macd, calculate_vwap, detect_candle_patterns

def multi_timeframe_analysis(indicators: Dict, ohlcv_data: Dict) -> Dict:
    """Perform multi-timeframe analysis for signal agreement."""
    results = {'15m': {}, '1h': {}, '4h': {}, '1d': {}}
    agreement_count = 0
    total_timeframes = len(results)

    for timeframe in results:
        # Calculate indicators for each timeframe
        ohlcv = ohlcv_data[timeframe]
        rsi = calculate_rsi(ohlcv)
        macd = calculate_macd(ohlcv)
        vwap = calculate_vwap(ohlcv)
        candle_patterns = detect_candle_patterns(ohlcv)

        # Determine signal direction
        direction = None
        if rsi[-1] > 70 and macd['signal'][-1] > macd['macd'][-1]:
            direction = 'SHORT'
        elif rsi[-1] < 30 and macd['signal'][-1] < macd['macd'][-1]:
            direction = 'LONG'
        elif any(p in ['bullish_engulfing', 'hammer'] for p in candle_patterns):
            direction = 'LONG'
        elif any(p in ['bearish_engulfing', 'shooting_star'] for p in candle_patterns):
            direction = 'SHORT'

        results[timeframe] = {
            'direction': direction,
            'rsi': rsi[-1],
            'macd': macd,
            'vwap': vwap[-1],
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
