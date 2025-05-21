# Updated model/predictor.py to address TP1 1-2% hit, Trade Duration, soft conditions, MACD zero fix, and Trade Type: None
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

class SignalPredictor:
    def __init__(self):
        self.min_data_points = 50  # Increased for MACD fix
        logger.info("Signal Predictor initialized")

    # Add Trade Duration based on timeframe
    def get_trade_duration(self, timeframe: str) -> str:
        durations = {
            '15m': 'Up to 1 hour',
            '1h': 'Up to 6 hours',
            '4h': 'Up to 24 hours',
            '1d': 'Up to 3 days'
        }
        return durations.get(timeframe, 'Unknown')

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
            logger.info(f"[{symbol}] {timeframe} - RSI: {latest['rsi']:.2f}, MACD: {latest['macd']:.2f}, MACD Signal: {latest['macd_signal']:.2f}, ADX: {latest['adx']:.2f}, Close: {latest['close']:.2f}")

            # Soften conditions
            if latest['rsi'] < 42:  # Softened from 35
                conditions.append("Oversold RSI")
            elif latest['rsi'] > 58:  # Softened from 65
                conditions.append("Overbought RSI")

            if latest['macd'] > latest['macd_signal']:  # Removed zero check for MACD
                conditions.append("Bullish MACD")
            elif latest['macd'] < latest['macd_signal']:
                conditions.append("Bearish MACD")

            if latest['adx'] > 8:  # Softened from 20
                conditions.append("Strong Trend")

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

            # Support/Resistance proximity (softened range to 10%)
            current_price = latest['close']
            support = sr_levels['support']
            resistance = sr_levels['resistance']
            if abs(current_price - support) / current_price < 0.1:  # Softened from 0.03
                conditions.append("Near Support")
            if abs(current_price - resistance) / current_price < 0.1:
                conditions.append("Near Resistance")

            # Volume confirmation (softened to 1.05x)
            if 'volume_sma_20' in latest and latest['volume'] > latest['volume_sma_20'] * 1.05:
                conditions.append("High Volume")

            logger.info(f"[{symbol}] {timeframe} - Conditions: {', '.join(conditions) if conditions else 'None'}")

            # Confidence calculation with adjusted weights
            confidence = 40.0  # Lowered base confidence
            if "Bullish MACD" in conditions or "Bearish MACD" in conditions:
                confidence += 15.0
            if "Bullish Engulfing" in conditions or "Bearish Engulfing" in conditions or "Hammer" in conditions or "Shooting Star" in conditions:
                confidence += 15.0
            if "Strong Trend" in conditions:
                confidence += 8.0
            if "Near Support" in conditions or "Near Resistance" in conditions:
                confidence += 10.0
            if "High Volume" in conditions:
                confidence += 10.0
            if "Oversold RSI" in conditions or "Overbought RSI" in conditions:
                confidence += 5.0
            if "Three White Soldiers" in conditions or "Three Black Crows" in conditions:
                confidence += 15.0
            if "Doji" in conditions:
                confidence += 5.0

            # Require minimum 3 conditions to avoid false signals
            if len(conditions) < 3:
                logger.info(f"[{symbol}] Insufficient conditions ({len(conditions)}) for {timeframe}")
                return None

            # Direction logic
            direction = None
            bullish_conditions = ["Bullish MACD", "Oversold RSI", "Bullish Engulfing", "Hammer", "Near Support", "Three White Soldiers"]
            bearish_conditions = ["Bearish MACD", "Overbought RSI", "Bearish Engulfing", "Shooting Star", "Near Resistance", "Three Black Crows"]
            if any(c in conditions for c in bullish_conditions) and confidence >= 40.0:
                direction = "LONG"
            elif any(c in conditions for c in bearish_conditions) and confidence >= 40.0:
                direction = "SHORT"

            if not direction:
                logger.info(f"[{symbol}] No clear direction for {timeframe}")
                return None

            # Calculate TP/SL for 1-2% TP1
            atr = latest.get('atr', max(0.1 * latest['close'], 0.02))  # Increased ATR fallback
            entry = current_price
            if direction == "LONG":
                tp1 = entry + max(0.01 * entry, 0.5 * atr)  # Ensure 1-2% for TP1
                tp2 = entry + max(0.015 * entry, 1.0 * atr)
                tp3 = entry + max(0.02 * entry, 2.0 * atr)
                sl = entry - max(0.008 * entry, 0.8 * atr)  # Tight SL
            else:  # SHORT
                tp1 = entry - max(0.01 * entry, 0.5 * atr)
                tp2 = entry - max(0.015 * entry, 1.0 * atr)
                tp3 = entry - max(0.02 * entry, 2.0 * atr)
                sl = entry + max(0.008 * entry, 0.8 * atr)

            # Ensure TP1 is within 1-2% range
            tp1_percent = abs(tp1 - entry) / entry * 100
            if not (1.0 <= tp1_percent <= 2.0):
                logger.warning(f"[{symbol}] TP1 out of 1-2% range ({tp1_percent:.2f}%), adjusting")
                if direction == "LONG":
                    tp1 = entry + 0.015 * entry  # Set to 1.5%
                else:
                    tp1 = entry - 0.015 * entry

            trade_type = classify_trade(confidence) or "Scalping"  # Default to Scalping

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
                'tp1_possibility': 70.0 if confidence > 75 else 60.0,
                'tp2_possibility': 50.0 if confidence > 75 else 40.0,
                'tp3_possibility': 30.0 if confidence > 75 else 20.0,
                'volume': float(latest['volume']),
                'trade_type': trade_type,
                'trade_duration': self.get_trade_duration(timeframe),  # Added Trade Duration
                'timestamp': pd.Timestamp.now().isoformat()
            }

            logger.info(f"[{symbol}] Signal generated for {timeframe}: {direction}, Confidence: {signal['confidence']}%, TP1: {signal['tp1']:.4f} ({tp1_percent:.2f}%)")
            return signal

        except Exception as e:
            logger.error(f"[{symbol}] Error predicting signal for {timeframe}: {str(e)}")
            return None
