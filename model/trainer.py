import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from joblib import dump
import os
import asyncio
from core.indicators import calculate_indicators
from data.collector import fetch_realtime_data
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = "ml_models/rf_model.joblib"

def detect_candle_patterns(df):
    patterns = []
    for i in range(1, len(df)):
        open_price = df['open'].iloc[i]
        close_price = df['close'].iloc[i]
        prev_open = df['open'].iloc[i-1]
        pattern = []
        if close_price > open_price and prev_open < close_price:
            pattern.append('bullish_engulfing')
        elif close_price < open_price and prev_open > open_price:
            pattern.append('bearish_engulfing')
        patterns.append(pattern)
    return patterns

async def prepare_training_data(symbol: str, timeframe: str = '15m', limit: int = 500):
    try:
        ohlcv = await fetch_realtime_data(symbol, timeframe, limit)
        if ohlcv is None or len(ohlcv) < 360:
            logger.warning(f"[{symbol}] Insufficient data")
            return None, None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df)

        patterns = detect_candle_patterns(df)
        df['bullish_engulfing'] = [1 if 'bullish_engulfing' in p else 0 for p in patterns] + [0]
        df['bearish_engulfing'] = [1 if 'bearish_engulfing' in p else 0 for p in patterns] + [0]

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
            "bullish_engulfing", "bearish_engulfing"
        ]
        X = df[features]
        y = df["label"]
        logger.info(f"[{symbol}] Prepared training data with {len(X)} samples")
        return X, y
    except Exception as e:
        logger.error(f"[{symbol}] Error preparing training data: {str(e)}")
        return None, None

async def train_model(symbol: str, timeframe: str = '15m', limit: int = 500):
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
        dump(model, MODEL_PATH)
        logger.info(f"[{symbol}] Model saved to {MODEL_PATH}")
        return True
    except Exception as e:
        logger.error(f"[{symbol}] Error training model: {str(e)}")
        return False

if __name__ == "__main__":
    async def main():
        symbol = "BTC/USDT"
        await train_model(symbol)
    asyncio.run(main())
