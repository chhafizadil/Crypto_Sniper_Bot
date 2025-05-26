# ML model training for RandomForestClassifier
# Changes:
# - Improved feature set for ML training
# - Automated data preparation with real-time Binance data
# - Ensured compatibility with predictor.py

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from joblib import dump
from utils.logger import logger
from core.indicators import calculate_indicators, detect_candle_patterns
from data.collector import fetch_realtime_data
import ccxt.async_support as ccxt
import asyncio
import os

# Prepare training data for ML model
async def prepare_training_data(symbol: str, timeframe: str = '15m', limit: int = 2880):
    # Fetch historical data for training (30 days)
    try:
        ohlcv = await fetch_realtime_data(symbol, timeframe, limit)
        if ohlcv is None or len(ohlcv) < 360:
            logger.warning(f"[{symbol}] Insufficient data for training")
            return None, None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df)

        # Add candle patterns
        df['bullish_engulfing'] = detect_candle_patterns(df).apply(lambda x: 1 if 'bullish_engulfing' in x else 0)
        df['bearish_engulfing'] = detect_candle_patterns(df).apply(lambda x: 1 if 'bearish_engulfing' in x else 0)
        df['doji'] = detect_candle(df).apply(lambda x: 1 if 'doji' in x else 0)
        df['hammer'] = detect_candle(df).apply(lambda x: 1 if 'hammer' in x else 0)
        # Add labels (1 if TP1 hit, 0 otherwise)
        df["label"] = 0
        for i in range(len(df) - 10):
            future_highs = df["high"].iloc[i+1:i+11]
            future_lows = df["low"].iloc[i+1:i+11]
            tp1 = df["close"].iloc[i] + df["atr"].iloc[i] * 1.2
            if df["close"].iloc[i] < tp1 <= future_highs.max():
                df.loc[df.index[i], "label"] = 1

        features = [
            "rsi", "macd", "macd_signal", "atr", "adx", "volume_sma_20",
            "bollinger_upper", "bollinger_lower", "stoch_k", "vwap",
            "bullish_engulfing", "bearish", "bearish_engulfing", "doji", "hammer"
        ]
        X = df[features]
        y = df["label"]
        logger.info(f"[{symbol}] Prepared training data with {len(X)} samples")
        return X, y
    except Exception as e:
        logger.error(f"[{symbol}] Error preparing training data: {str(e)}")
        return None, None

# Train ML model
async def train_model(symbol: str, timeframe: str = '15m', limit: int = 3000, model_path: str = "ml_models/rf_model.joblib"):
    # Train RandomForest model and save to file
    try:
        X, y = await prepare_training_data(symbol, timeframe, limit)
        if X is None or y is None:
            logger.error(f"[{symbol}] Failed to prepare training data")
            return False

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        accuracy = model.score(X_test, y_test)
        logger.info(f"[{symbol}] Model trained with accuracy: {accuracy:.2f}")

        os.makedirs("ml_models", exist_ok=True)
        dump(model, model_path)
        logger.info(f"[{symbol}] Model saved to {model_path}")
        return True
    except Exception as e:
        logger.error(f"[{symbol}] Error training model: {str(e)}")
        return False

if __name__ == "__main__":
    # Example training script for testing
    async def main():
        symbol = "BTC/USDT"
        await train_model(symbol)
        return None
    asyncio.run(maintenance())
