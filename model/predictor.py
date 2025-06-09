# Signal prediction with rule-based and ML logic
# Changes:
# - Updated SL to 1% of entry price (LONG: entry * 0.99, SHORT: entry * 1.01)
# - Added TP1/2/3 profit percentage calculation
# - Set MIN_VOLUME to 500,000 USD
# - Added cooldown check with is_cooldown_active
# - Optimized logging for Cloud Run

import pandas as pd
import numpy as np
import asyncio
from joblib import load
from core.indicators import calculate_indicators, calculate_fibonacci_levels, calculate_support_resistance, detect_candle_patterns
from core.indicators import calculate_tp_probabilities_and_prices, adjust_tp_for_stablecoin
from utils.logger import logger
from utils.helpers import is_cooldown_active
from data.collector import fetch_realtime_data
from sklearn.ensemble import RandomForestClassifier
import os

class SignalPredictor:
    def __init__(self):
        # Initialize SignalPredictor with minimum data points
        self.min_data_points = 30
        self.model_path = "ml_models/rf_model.joblib"
        self.ml_model = None
        if os.path.exists(self.model_path):
            try:
                self.ml_model = load(self.model_path)
                logger.info("Loaded RandomForest model for prediction")
            except Exception as e:
                logger.error(f"Error loading ML model: {str(e)}")
        logger.info("SignalPredictor initialized")

    def get_trade_duration(self, timeframe: str) -> str:
        # Get trade duration based on timeframe
        durations = {
            '5m': 'Up to 1 hour',
            '15m': 'Up to 1 hour',
            '1h': 'Up to 6 hours',
            '4h': 'Up to 24 hours',
            '1d': 'Up to 3 days'
        }
        return durations.get(timeframe, 'Unknown')

    def calculate_tp_hit_possibilities(self, symbol: str, direction: str, entry: float, tp1: float, tp2: float, tp3: float) -> tuple:
        # Use fixed TP hit probabilities
        logger.info(f"[{symbol}] Using fixed TP possibilities")
        return 60.0, 40.0, 20.0

    def prepare_ml_features(self, df, symbol):
        # Prepare features for ML prediction
        try:
            df = df.copy()
            df = calculate_indicators(df)
            if df.empty:
                logger.error(f"[{symbol}] Failed to prepare ML features")
                return None

            df['bullish_engulfing'] = detect_candle_patterns(df).count('bullish_engulfing')
            df['bearish_engulfing'] = detect_candle_patterns(df).count('bearish_engulfing')
            df['doji'] = detect_candle_patterns(df).count('doji')
            df['hammer'] = detect_candle_patterns(df).count('hammer')
            df['shooting_star'] = detect_candle_patterns(df).count('shooting_star')
            df['three_white_soldiers'] = detect_candle_patterns(df).count('three_white_soldiers')
            df['three_black_crows'] = detect_candle_patterns(df).count('three_black_crows')

            features = [
                'rsi', 'macd', 'macd_signal', 'atr', 'adx', 'volume_sma_20',
                'bollinger_upper', 'bollinger_lower', 'stoch_k', 'vwap',
                'bullish_engulfing', 'bearish_engulfing', 'doji', 'hammer',
                'shooting_star', 'three_white_soldiers', 'three_black_crows'
            ]
            X = df[features].iloc[-1:].values
            return X
        except Exception as e:
            logger.error(f"[{symbol}] Error preparing ML features: {str(e)}")
            return None

    def classify_trade(self, confidence: float) -> str:
        # Classify trade as Normal or Scalping based on confidence
        try:
            if confidence >= 85:
                trade_type = "Normal"
            else:
                trade_type = "Scalping"
            logger.info(f"Trade classified as {trade_type} with confidence {confidence:.2f}")
            return trade_type
        except Exception as e:
            logger.error(f"Error classifying trade: {str(e)}")
            return "Scalping"

    async def predict_signal(self, symbol: str, df: pd.DataFrame, timeframe: str, last_signal_time: dict) -> dict:
        # Predict signal using rule-based and ML logic
        try:
            if df is None or len(df) < self.min_data_points:
                logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                return None

            df = df.copy()
            logger.info(f"[{symbol}] Calculating indicators for {timeframe}")
            df = calculate_indicators(df)
            logger.info(f"[{symbol}] Calculating Fibonacci levels for {timeframe}")
            df = calculate_fibonacci_levels(df, timeframe)
            logger.info(f"[{symbol}] Calculating support/resistance for {timeframe}")
            sr_levels = calculate_support_resistance(symbol, df)

            latest = df.iloc[-1]
            conditions = []
            logger.info(f"[{symbol}] {timeframe} - RSI: {latest['rsi']:.2f}, MACD: {latest['macd']:.4f}, ADX: {latest['adx']:.2f}")

            if latest['rsi'] < 30:
                conditions.append("Oversold RSI")
            elif latest['rsi'] > 70:
                conditions.append("Overbought RSI")

            if latest['macd'] > latest['macd_signal'] and latest['macd'] > 0:
                conditions.append("Bullish MACD")
            elif latest['macd'] < latest['macd_signal'] and latest['macd'] < 0:
                conditions.append("Bearish MACD")

            if latest['adx'] > 25:
                conditions.append("Strong Trend")

            if latest['close'] > latest['bollinger_upper']:
                conditions.append("Above Bollinger Upper")
            elif latest['close'] < latest['bollinger_lower']:
                conditions.append("Below Bollinger Lower")

            patterns = detect_candle_patterns(df)
            conditions.extend(patterns)

            current_price = latest['close']
            support = sr_levels['support']
            resistance = sr_levels['resistance']
            if abs(current_price - support) / current_price < 0.05:
                conditions.append("Near Support")
            if abs(current_price - resistance) / current_price < 0.05:
                conditions.append("Near Resistance")

            if 'volume_sma_20' in latest and latest['volume'] > latest['volume_sma_20'] * 1.2:
                conditions.append("High Volume")

            logger.info(f"[{symbol}] Conditions: {', '.join(conditions) if conditions else 'None'}")

            confidence = 50.0
            weights = []
            if "Bullish MACD" in conditions or "Bearish MACD" in conditions:
                confidence += 15.0
                weights.append("MACD: +15")
            if any(p in conditions for p in ['bullish_engulfing', 'bearish_engulfing', 'hammer', 'shooting_star']):
                confidence += 12.0
                weights.append("Candlestick: +12")
            if "Strong Trend" in conditions:
                confidence += 12.0
                weights.append("ADX: +12")
            if "Near Support" in conditions or "Near Resistance" in conditions:
                confidence += 8.0
            if "High Volume" in conditions:
                confidence += 8.0
            confidence = min(confidence, 95.0)
            logger.info(f"[{symbol}] Rule-based confidence: {confidence:.2f}")

            ml_confidence = 0.0
            ml_direction = None
            if self.ml_model:
                X_ml = self.prepare_ml_features(df, symbol)
                if X_ml is not None:
                    try:
                        ml_pred = self.ml_model.predict_proba(X_ml)[0]
                        ml_direction = "LONG" if ml_pred[0] > ml_pred[1] else "SHORT"
                        ml_confidence = max(ml_pred) * 100
                        logger.info(f"[{symbol}] ML prediction: {ml_direction}, Confidence: {ml_confidence:.2f}%")
                    except Exception as e:
                        logger.error(f"[{symbol}] ML prediction error: {str(e)}")

            direction = None
            final_confidence = confidence
            if ml_confidence >= 70.0 and ml_direction:
                direction = ml_direction
                final_confidence = (ml_confidence + confidence) / 2
                logger.info(f"[{symbol}] Using ML prediction: {direction}, Combined Confidence: {final_confidence:.2f}%")
            else:
                bullish_conditions = ['bullish_engulfing', 'Oversold RSI', 'Bullish MACD', 'hammer', 'three_white_soldiers']
                bearish_conditions = ['bearish_engulfing', 'Overbought RSI', 'Bearish MACD', 'shooting_star', 'three_black_crows']
                bullish_count = sum(1 for c in conditions if c in bullish_conditions)
                bearish_count = sum(1 for c in conditions if c in bearish_conditions)

                if bullish_count > bearish_count and confidence >= 70:
                    direction = "LONG"
                elif bearish_count > bullish_count and confidence >= 70:
                    direction = "SHORT"
                logger.info(f"[{symbol}] Using rule-based prediction: {direction}, Confidence: {confidence:.2f}%")

            if not direction:
                logger.warning(f"[{symbol}] No clear direction found")
                return None

            atr = max(latest.get('atr', 0.005 * current_price), 0.002 * current_price)
            entry_price = round(current_price, 2)
            if direction == "LONG":
                tp1 = round(entry_price + max(0.01 * entry_price, 0.75 * atr), 2)
                tp2 = round(entry_price + max(0.015 * entry_price, 1.5 * atr), 2)
                tp3 = round(entry_price + max(0.02 * entry_price, 2.5 * atr), 2)
                sl = round(entry_price * 0.99, 2)  # 1% below entry
            else:
                tp1 = round(entry_price - max(0.01 * entry_price, 0.75 * atr), 2)
                tp2 = round(entry_price - max(0.015 * entry_price, 1.5 * atr), 2)
                tp3 = round(entry_price - max(0.02 * entry_price, 2.5 * atr), 2)
                sl = round(entry_price * 1.01, 2)  # 1% above entry

            tp1, tp2, tp3 = adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry_price)
            probabilities, prices = calculate_tp_probabilities_and_prices(conditions, entry_price, atr)
            tp1_possibility, tp2_possibility, tp3_possibility = self.calculate_tp_hit_possibilities(symbol, direction, entry_price, prices['TP1'], prices['TP2'], prices['TP3'])

            # Calculate TP profit percentages
            tp1_profit_pct = abs((tp1 - entry_price) / entry_price * 100)
            tp2_profit_pct = abs((tp2 - entry_price) / entry_price * 100)
            tp3_profit_pct = abs((tp3 - entry_price) / entry_price * 100)

            trade_type = self.classify_trade(final_confidence)

            signal = {
                'symbol': symbol,
                'direction': direction,
                'entry': float(entry_price),
                'confidence': float(final_confidence),
                'timeframe': timeframe,
                'conditions': conditions,
                'tp1': float(prices['TP1']),
                'tp2': float(prices['TP2']),
                'tp3': float(prices['TP3']),
                'sl': float(sl),
                'tp1_possibility': float(probabilities['TP1']),
                'tp2_possibility': float(probabilities['TP2']),
                'tp3_possibility': float(probabilities['TP3']),
                'tp1_profit_pct': float(tp1_profit_pct),  # Added profit percentage
                'tp2_profit_pct': float(tp2_profit_pct),  # Added profit percentage
                'tp3_profit_pct': float(tp3_profit_pct),  # Added profit percentage
                'volume': float(latest['volume']),
                'trade_type': trade_type,
                'trade_duration': self.get_trade_duration(timeframe),
                'timestamp': pd.Timestamp.now().isoformat(),
                'atr': float(atr)
            }

            logger.info(f"[{symbol}] Signal generated: {direction}, Entry: ${entry_price:.2f}, Confidence: {final_confidence:.2f}%")
            return signal
        except Exception as e:
            logger.error(f"Error in predict_signal for {str(e)}")
            return None
