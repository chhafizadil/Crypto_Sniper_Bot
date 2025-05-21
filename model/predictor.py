import pandas as pd
import numpy as np
import asyncio
from core.indicators import calculate_indicators
from core.candle_patterns import (
    is_bullish_engulfing, is_bearish_engulfing, is_doji,
    is_hammer, is_shooting_star, is_three_white_soldiers, is_three_black_crows
)
from utils.fibonacci import calculate_fibonacci_levels
from utils.support_resistance import calculate_support_resistance
from core.trade_classifier import classify_trade
from utils.logger import logger
import os

class SignalPredictor:
    def __init__(self):
        self.min_data_points = 50
        logger.info("Signal Predictor initialized")

    def get_trade_duration(self, timeframe: str) -> str:
        durations = {
            '5m': 'Up to 1 hour',
            '15m': 'Up to 1 hour',
            '1h': 'Up to 6 hours',
            '4h': 'Up to 24 hours',
            '1d': 'Up to 3 days'
        }
        return durations.get(timeframe, 'Unknown')

    def calculate_tp_hit_possibilities(self, symbol: str, direction: str, entry: float, tp1: float, tp2: float, tp3: float) -> tuple:
        try:
            file_path = 'logs/signals_log_new.csv'
            if not os.path.exists(file_path):
                logger.warning(f"[{symbol}] No historical signals for TP hit calculation")
                return 60.0, 40.0, 20.0

            df = pd.read_csv(file_path)
            if 'symbol' not in df.columns:
                logger.error(f"[{symbol}] 'symbol' column missing in signals_log_new.csv")
                return 60.0, 40.0, 20.0

            df = df[df['symbol'] == symbol]
            if df.empty:
                logger.warning(f"[{symbol}] No historical signals for this symbol")
                return 60.0, 40.0, 20.0

            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df[df['timestamp'] >= pd.Timestamp.now() - pd.Timedelta(days=30)]
            df = df[df['direction'] == direction]

            if df.empty:
                logger.warning(f"[{symbol}] No recent signals for {direction}")
                return 60.0, 40.0, 20.0

            tp1_hits = len(df[df['tp1_hit'] == True]) if 'tp1_hit' in df else 0
            tp2_hits = len(df[df['tp2_hit'] == True]) if 'tp2_hit' in df else 0
            tp3_hits = len(df[df['tp3_hit'] == True]) if 'tp3_hit' in df else 0
            total_signals = len(df)

            tp1_possibility = (tp1_hits / total_signals * 100) if total_signals > 0 else 60.0
            tp2_possibility = (tp2_hits / total_signals * 100) if total_signals > 0 else 40.0
            tp3_possibility = (tp3_hits / total_signals * 100) if total_signals > 0 else 20.0

            tp1_distance = abs(tp1 - entry) / entry * 100
            tp2_distance = abs(tp2 - entry) / entry * 100
            tp3_distance = abs(tp3 - entry) / entry * 100
            tp1_possibility *= min(1.0, 2.0 / max(tp1_distance, 0.01))  # Avoid division by zero
            tp2_possibility *= min(1.0, 3.0 / max(tp2_distance, 0.01))
            tp3_possibility *= min(1.0, 4.0 / max(tp3_distance, 0.01))

            return max(min(tp1_possibility, 95.0), 50.0), max(min(tp2_possibility, 80.0), 30.0), max(min(tp3_possibility, 60.0), 10.0)
        except Exception as e:
            logger.error(f"[{symbol}] Error calculating TP hit possibilities: {str(e)}")
            return 60.0, 40.0, 20.0

    async def predict_signal(self, symbol: str, df: pd.DataFrame, timeframe: str) -> dict:
        try:
            if df is None or len(df) < self.min_data_points:
                logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                return None

            df = df.copy()
            logger.info(f"[{symbol}] Calculating indicators for {timeframe}")
            df = calculate_indicators(df)
            logger.info(f"[{symbol}] Calculating Fibonacci levels for {timeframe}")
            df = calculate_fibonacci_levels(df)
            logger.info(f"[{symbol}] Calculating support/resistance for {timeframe}")
            sr_levels = calculate_support_resistance(symbol, df)

            latest = df.iloc[-1]
            conditions = []
            logger.info(f"[{symbol}] {timeframe} - RSI: {latest['rsi']:.2f}, MACD: {latest['macd']:.4f}, MACD Signal: {latest['macd_signal']:.4f}, ADX: {latest['adx']:.2f}, Close: {latest['close']:.2f}")

            # RSI conditions
            if latest['rsi'] < 30:
                conditions.append("Oversold RSI")
            elif latest['rsi'] > 70:
                conditions.append("Overbought RSI")

            # MACD conditions
            if abs(latest['macd']) < 1e-5:
                logger.warning(f"[{symbol}] MACD near zero, relying on RSI/ADX")
            else:
                if latest['macd'] > latest['macd_signal'] and latest['macd'] > 0:
                    conditions.append("Bullish MACD")
                elif latest['macd'] < latest['macd_signal'] and latest['macd'] < 0:
                    conditions.append("Bearish MACD")

            # ADX condition
            if latest['adx'] > 25:
                conditions.append("Strong Trend")

            # Bollinger Bands
            if latest['close'] > latest['bollinger_upper']:
                conditions.append("Above Bollinger Upper")
            elif latest['close'] < latest['bollinger_lower']:
                conditions.append("Below Bollinger Lower")

            # Stochastic Oscillator
            if latest['stoch_k'] < 20 and latest['stoch_k'] < latest['stoch_d']:
                conditions.append("Oversold Stochastic")
            elif latest['stoch_k'] > 80 and latest['stoch_k'] > latest['stoch_d']:
                conditions.append("Overbought Stochastic")

            # VWAP
            if latest['close'] > latest['vwap']:
                conditions.append("Above VWAP")
            elif latest['close'] < latest['vwap']:
                conditions.append("Below VWAP")

            # Candlestick patterns
            if is_bullish_engulfing(df).iloc[-1]:
                conditions.append("Bullish Engulfing")
            if is_bearish_engulfing(df).iloc[-1]:
                conditions.append("Bearish Engulfing")
            if is_doji(df).iloc[-1]:
                conditions.append("Doji")
            if is_hammer(df).iloc[-1]:
                conditions.append("Hammer")
            if is_shooting_star(df).iloc[-1]:
                conditions.append("Shooting Star")
            if is_three_white_soldiers(df).iloc[-1]:
                conditions.append("Three White Soldiers")
            if is_three_black_crows(df).iloc[-1]:
                conditions.append("Three Black Crows")

            # Support/Resistance proximity
            current_price = latest['close']
            support = sr_levels['support']
            resistance = sr_levels['resistance']
            if abs(current_price - support) / current_price < 0.05:
                conditions.append("Near Support")
            if abs(current_price - resistance) / current_price < 0.05:
                conditions.append("Near Resistance")

            # Volume confirmation
            if 'volume_sma_20' in latest and latest['volume'] > latest['volume_sma_20'] * 1.2:
                conditions.append("High Volume")

            logger.info(f"[{symbol}] {timeframe} - Conditions: {', '.join(conditions) if conditions else 'None'}")

            # Confidence calculation with weights logging
            confidence = 50.0
            weights = []
            if "Bullish MACD" in conditions or "Bearish MACD" in conditions:
                confidence += 20.0
                weights.append("MACD: +20")
            if "Bullish Engulfing" in conditions or "Bearish Engulfing" in conditions or "Hammer" in conditions or "Shooting Star" in conditions:
                confidence += 15.0
                weights.append("Candlestick: +15")
            if "Strong Trend" in conditions:
                confidence += 15.0
                weights.append("ADX: +15")
            if "Near Support" in conditions or "Near Resistance" in conditions:
                confidence += 10.0
                weights.append("S/R: +10")
            if "High Volume" in conditions:
                confidence += 10.0
                weights.append("Volume: +10")
            if "Oversold RSI" in conditions or "Overbought RSI" in conditions:
                confidence += 10.0
                weights.append("RSI: +10")
            if "Three White Soldiers" in conditions or "Three Black Crows" in conditions:
                confidence += 15.0
                weights.append("Three Soldiers/Crows: +15")
            if "Doji" in conditions:
                confidence += 5.0
                weights.append("Doji: +5")
            if "Above Bollinger Upper" in conditions or "Below Bollinger Lower" in conditions:
                confidence += 10.0
                weights.append("Bollinger: +10")
            if "Oversold Stochastic" in conditions or "Overbought Stochastic" in conditions:
                confidence += 10.0
                weights.append("Stochastic: +10")
            if "Above VWAP" in conditions or "Below VWAP" in conditions:
                confidence += 5.0
                weights.append("VWAP: +5")

            confidence = min(confidence, 100.0)
            logger.info(f"[{symbol}] {timeframe} - Confidence: {confidence:.2f}, Weights: {', '.join(weights) if weights else 'None'}")

            # Direction logic
            direction = None
            bullish_conditions = ["Bullish MACD", "Oversold RSI", "Bullish Engulfing", "Hammer", "Near Support", "Three White Soldiers", "Below Bollinger Lower", "Oversold Stochastic", "Above VWAP"]
            bearish_conditions = ["Bearish MACD", "Overbought RSI", "Bearish Engulfing", "Shooting Star", "Near Resistance", "Three Black Crows", "Above Bollinger Upper", "Overbought Stochastic", "Below VWAP"]
            bullish_count = sum(1 for c in conditions if c in bullish_conditions)
            bearish_count = sum(1 for c in conditions if c in bearish_conditions)

            if bullish_count > bearish_count and confidence >= 65 and len(conditions) >= 3:
                direction = "LONG"
            elif bearish_count > bullish_count and confidence >= 65 and len(conditions) >= 3:
                direction = "SHORT"

            if not direction:
                logger.info(f"[{symbol}] No clear direction: Bullish={bullish_count}, Bearish={bearish_count}, Confidence={confidence:.2f}, Conditions={len(conditions)}")
                return None

            # Calculate TP/SL
            atr = max(latest.get('atr', 0.005 * current_price), 0.01 * current_price)  # Ensure ATR is at least 1% of price
            entry = round(current_price, 2)
            if direction == "LONG":
                tp1 = round(entry + max(0.01 * entry, 0.75 * atr), 2)
                tp2 = round(entry + max(0.015 * entry, 1.5 * atr), 2)
                tp3 = round(entry + max(0.02 * entry, 2.5 * atr), 2)
                sl = round(entry - max(0.008 * entry, 1.0 * atr), 2)
            else:
                tp1 = round(entry - max(0.01 * entry, 0.75 * atr), 2)
                tp2 = round(entry - max(0.015 * entry, 1.5 * atr), 2)
                tp3 = round(entry - max(0.02 * entry, 2.5 * atr), 2)
                sl = round(entry + max(0.008 * entry, 1.0 * atr), 2)

            # Ensure TP1 is within 1-2% range
            tp1_percent = abs(tp1 - entry) / entry * 100
            if not (1.0 <= tp1_percent <= 2.0):
                logger.warning(f"[{symbol}] TP1 out of 1-2% range ({tp1_percent:.2f}%), adjusting")
                tp1 = round(entry + 0.015 * entry if direction == "LONG" else entry - 0.015 * entry, 2)

            # Calculate dynamic TP hit possibilities
            tp1_possibility, tp2_possibility, tp3_possibility = self.calculate_tp_hit_possibilities(symbol, direction, entry, tp1, tp2, tp3)

            trade_type = classify_trade(confidence) or "Scalping"

            signal = {
                'symbol': symbol,
                'direction': direction,
                'entry': float(entry),
                'confidence': float(confidence),
                'timeframe': timeframe,
                'conditions': conditions,
                'tp1': float(tp1),
                'tp2': float(tp2),
                'tp3': float(tp3),
                'sl': float(sl),
                'tp1_possibility': float(tp1_possibility),
                'tp2_possibility': float(tp2_possibility),
                'tp3_possibility': float(tp3_possibility),
                'volume': float(latest['volume']),
                'trade_type': trade_type,
                'trade_duration': self.get_trade_duration(timeframe),
                'timestamp': pd.Timestamp.now().isoformat()
            }

            logger.info(f"[{symbol}] Signal generated for {timeframe}: {direction}, Confidence: {signal['confidence']:.2f}%, TP1: {signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)")
            return signal

        except Exception as e:
            logger.error(f"[{symbol}] Error predicting signal for {timeframe}: {str(e)}")
            return None
