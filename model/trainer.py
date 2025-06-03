# ML model training for RandomForestClassifier
# Fixes:
# - Fixed detect_candle to detect_candle_patterns
# - Added missing json import
# - Moved logger import after definition
# - Reduced limit to 500 candles for Replit
# - Made Cloud Storage optional for Replit

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from joblib import dump, load
import json
import os
import asyncio
from core.indicators import calculate_indicators, detect_candle_patterns
from data.collector import fetch_realtime_data
import ccxt.async_support as ccxt
try:
    from google.cloud import storage
except ImportError:
    storage = None

# Logger setup
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloud Storage setup (optional for Replit)
storage_client = None
BUCKET_NAME = "crypto-sniper-bot-models"
MODEL_PATH = "ml_models/rf_model.joblib"
GCS_MODEL_PATH = "models/rf_model.joblib"
if storage:
    try:
        storage_client = storage.Client()
    except Exception as e:
        logger.error(f"Cloud Storage initialization failed: {str(e)}")

async def prepare_training_data(symbol: str, timeframe: str = '15m', limit: int = 500):
    try:
        ohlcv = await fetch_realtime_data(symbol, timeframe, limit)
        if ohlcv is None or len(ohlcv) < 360:
            logger.warning(f"[{symbol}] Insufficient data for training")
            return None, None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df)

        df['bullish_engulfing'] = detect_candle_patterns(df).apply(lambda x: 1 if isinstance(x, list) and 'bullish_engulfing' in x else 0)
        df['bearish_engulfing'] = detect_candle_patterns(df).apply(lambda x: 1 if isinstance(x, list) and 'bearish_engulfing' in x else 0)
        df['doji'] = detect_candle_patterns(df).apply(lambda x: 1 if isinstance(x, list) and 'doji' in x else 0)
        df['hammer'] = detect_candle_patterns(df).apply(lambda x: 1 if isinstance(x, list) and 'hammer' in x else 0)

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
            "bullish_engulfing", "bearish_engulfing", "doji", "hammer"
        ]
        X = df[features]
        y = df["label"]
        logger.info(f"[{symbol}] Prepared training data with {len(X)} samples")
        return X, y
    except Exception as e:
        logger.error(f"[{symbol}] Error preparing training data: {str(e)}")
        return None, None

def save_to_gcs(model, bucket_name, destination_blob_name):
    if storage_client:
        try:
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)
            with blob.open("wb") as f:
                dump(model, f)
            logger.info(f"Model saved to gs://{bucket_name}/{destination_blob_name}")
        except Exception as e:
            logger.error(f"Error saving model to GCS: {str(e)}")

def load_from_gcs(bucket_name, source_blob_name):
    if storage_client:
        try:
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(source_blob_name)
            with blob.open("rb") as f:
                model = load(f)
            logger.info(f"Model loaded from gs://{bucket_name}/{source_blob_name}")
            return model
        except Exception as e:
            logger.error(f"Error loading model from GCS: {str(e)}")
    return None

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
        save_to_gcs(model, BUCKET_NAME, GCS_MODEL_PATH)
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
