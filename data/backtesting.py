import pandas as pd
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
import sqlite3
import asyncio

async def backtest_signals(symbol: str, timeframe: str = "1h", limit: int = 1000):
    try:
        logger.info(f"[{symbol}] Starting backtest for {timeframe}")
        df = await fetch_realtime_data(symbol, timeframe, limit=limit)
        if df is None or len(df) < 50:
            logger.warning(f"[{symbol}] Insufficient data for backtest")
            return None

        predictor = SignalPredictor()
        signals = []
        results = {
            "tp1_hit": 0,
            "tp2_hit": 0,
            "tp3_hit": 0,
            "sl_hit": 0,
            "pending": 0,
            "total_signals": 0,
            "avg_confidence": 0
        }

        for i in range(len(df) - 50, len(df) - 1):
            temp_df = df.iloc[:i+1]
            signal = await predictor.predict_signal(symbol, temp_df, timeframe)
            if signal:
                signals.append(signal)
                future_data = df.iloc[i+1:i+11]
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

                signal['status'] = status
                conn = sqlite3.connect('logs/signals.db')
                cursor = conn.cursor()
                conditions_str = ', '.join(signal['conditions']) if isinstance(signal.get('conditions'), list) else signal.get('conditions', '')
                cursor.execute('''
                    INSERT INTO signals (
                        symbol, direction, entry, confidence, timeframe, conditions,
                        tp1, tp2, tp3, sl, tp1_possibility, tp2_possibility,
                        tp3_possibility, volume, trade_type, trade_duration, timestamp,
                        status, hit_timestamp, quote_volume_24h, leverage, agreement
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    signal.get('symbol'), signal.get('direction'), signal.get('entry'),
                    signal.get('confidence'), signal.get('timeframe'), conditions_str,
                    signal.get('tp1'), signal.get('tp2'), signal.get('tp3'), signal.get('sl'),
                    signal.get('tp1_possibility'), signal.get('tp2_possibility'),
                    signal.get('tp3_possibility'), signal.get('volume'), signal.get('trade_type'),
                    signal.get('trade_duration'), signal.get('timestamp'), signal.get('status'),
                    signal.get('hit_timestamp'), signal.get('quote_volume_24h'), signal.get('leverage'),
                    signal.get('agreement')
                ))
                conn.commit()
                conn.close()
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

async def run_backtesting_for_all_symbols():
    try:
        exchange = ccxt.async_support.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True
        })
        timeframes = ['1h', '4h', '1d']
        high_volume_symbols = await get_high_volume_symbols(exchange, MIN_QUOTE_VOLUME)
        for symbol in high_volume_symbols[:10]:  # Limit to top 10 symbols
            for timeframe in timeframes:
                await backtest_signals(symbol, timeframe)
        await exchange.close()
    except Exception as e:
        logger.error(f"Error in backtesting loop: {str(e)}")

if __name__ == "__main__":
    from main import get_high_volume_symbols, MIN_QUOTE_VOLUME
    asyncio.run(run_backtesting_for_all_symbols())
