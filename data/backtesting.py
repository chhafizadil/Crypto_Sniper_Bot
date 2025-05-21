import pandas as pd
import ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger

async def backtest_signals(symbol: str, timeframe: str = "15m", limit: int = 1000):
    try:
        logger.info(f"[{symbol}] Starting backtest for {timeframe}")
        df = await fetch_realtime_data(symbol, timeframe, limit=limit)  # Use limit=1000
        if df is None or len(df) < 50:
            logger.warning(f"[{symbol}] Insufficient data for backtest")
            return None

        predictor = SignalPredictor()
        signals = []
        results = {"tp1_hit": 0, "tp2_hit": 0, "tp3_hit": 0, "sl_hit": 0, "pending": 0, "total_signals": 0, "avg_confidence": 0}

        for i in range(len(df) - 50, len(df) - 1):
            temp_df = df.iloc[:i+1]
            signal = await predictor.predict_signal(symbol, temp_df, timeframe)
            if signal:
                signals.append(signal)
                future_data = df.iloc[i+1:i+11]  # Next 10 candles
                if future_data.empty:
                    continue

                status = "pending"
                if signal['direction'] == "LONG":
                    future_highs = future_data['high']
                    future_lows = future_data['low']
                    if future_highs.max() >= signal['tp3']:
                        status = "tp3"
                    elif future_highs.max() >= signal['tp2']:
                        status = "tp2"
                    elif future_highs.max() >= signal['tp1']:
                        status = "tp1"
                    elif future_lows.min() <= signal['sl']:
                        status = "sl"
                else:  # SHORT
                    future_highs = future_data['high']
                    future_lows = future_data['low']
                    if future_lows.min() <= signal['tp3']:
                        status = "tp3"
                    elif future_lows.min() <= signal['tp2']:
                        status = "tp2"
                    elif future_lows.min() <= signal['tp1']:
                        status = "tp1"
                    elif future_highs.max() >= signal['sl']:
                        status = "sl"

                results[status] += 1
                results['total_signals'] += 1

        if results['total_signals'] > 0:
            results['avg_confidence'] = sum(s['confidence'] for s in signals) / len(signals)
            results['tp1_hit_rate'] = (results['tp1_hit'] + results['tp2_hit'] + results['tp3_hit']) / results['total_signals'] * 100
            results['tp2_hit_rate'] = (results['tp2_hit'] + results['tp3_hit']) / results['total_signals'] * 100
            results['tp3_hit_rate'] = results['tp3_hit'] / results['total_signals'] * 100
            results['sl_hit_rate'] = results['sl_hit'] / results['total_signals'] * 100

        logger.info(
            f"[{symbol}] Backtest Results:\n"
            f"Total Signals: {results['total_signals']}\n"
            f"TP1 Hit Rate: {results['tp1_hit_rate']:.2f}%\n"
            f"TP2 Hit Rate: {results['tp2_hit_rate']:.2f}%\n"
            f"TP3 Hit Rate: {results['tp3_hit_rate']:.2f}%\n"
            f"SL Hit Rate: {results['sl_hit_rate']:.2f}%\n"
            f"Average Confidence: {results['avg_confidence']:.2f}%"
        )
        return results
    except Exception as e:
        logger.error(f"[{symbol}] Error in backtest: {str(e)}")
        return None

if __name__ == "__main__":
    import asyncio
    symbol = "BTC/USDT"
    asyncio.run(backtest_signals(symbol))
