import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from joblib import dump
from utils.logger import logger
from core.candle_patterns import is_bullish_engulfing, is_bearish_engulfing, is_doji, is_hammer, is_shooting_star, is_three_white_soldiers, is_three_black_crows
import ccxt

def prepare_training_data(symbol, ohlcv):
    try:
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if len(df) < 50:
            logger(f"[{symbol}] Insufficient data for training", level='WARNING')
            return None, None

        df["rsi"] = pd.Series(np.full(len(df), 50.0))  # Placeholder
        df["macd"] = pd.Series(np.full(len(df), 0.0))
        df["macd_signal"] = pd.Series(np.full(len(df), 0.0))
        df["bb_upper"] = df["close"] * 1.02
        df["bb_lower"] = df["close"] * 0.98
        df["atr"] = (df["high"] - df["low"]).rolling(window=14).mean()
        df["volume_sma_20"] = df["volume"].rolling(window=20).mean()
        df["bullish_engulfing"] = df.apply(lambda x: is_bullish_engulfing(df.loc[:x.name]), axis=1).astype(int)
        df["bearish_engulfing"] = df.apply(lambda x: is_bearish_engulfing(df.loc[:x.name]), axis=1).astype(int)
        df["doji"] = df.apply(lambda x: is_doji(df.loc[:x.name]), axis=1).astype(int)
        df["hammer"] = df.apply(lambda x: is_hammer(df.loc[:x.name]), axis=1).astype(int)
        df["shooting_star"] = df.apply(lambda x: is_shooting_star(df.loc[:x.name]), axis=1).astype(int)
        df["three_white_soldiers"] = df.apply(lambda x: is_three_white_soldiers(df.loc[:x.name]), axis=1).astype(int)
        df["three_black_crows"] = df.apply(lambda x: is_three_black_crows(df.loc[:x.name]), axis=1).astype(int)

        # Label: 1 if TP1 hit, 0 otherwise
        df["label"] = 0
        for i in range(len(df) - 10):
            future_highs = df["high"].iloc[i+1:i+11]
            future_lows = df["low"].iloc[i+1:i+11]
            tp1 = df["close"].iloc[i] + df["atr"].iloc[i] * 1.2  # Example TP1
            if df["close"].iloc[i] < tp1 <= future_highs.max():
                df.loc[df.index[i], "label"] = 1

        features = [
            "rsi", "macd", "macd_signal", "bb_upper", "bb_lower", "atr",
            "volume", "volume_sma_20", "bullish_engulfing", "bearish_engulfing",
            "doji", "hammer", "shooting_star", "three_white_soldiers", "three_black_crows"
        ]
        X = df[features]
        y = df["label"]
        return X, y
    except Exception as e:
        logger(f"[{symbol}] Error preparing training data: {e}", level='ERROR')
        return None, None

def train_model(symbol, ohlcv, model_path="models/rf_model.joblib"):
    try:
        X, y = prepare_training_data(symbol, ohlcv)
        if X is None or y is None:
            return False

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        model = RandomForestClassifier(n_estimators=50, max_depth=10, random_state=42)
        model.fit(X_train, y_train)

        accuracy = model.score(X_test, y_test)
        logger(f"[{symbol}] Model trained with accuracy: {accuracy:.2f}")

        import os
        os.makedirs("models", exist_ok=True)
        dump(model, model_path)
        log(f"[{symbol}] Model saved to {model_path}")
        return True
    except Exception as e:
        logger(f"[{symbol}] Error training model: {e}", level='ERROR')
        return False

if __name__ == "__main__":
    exchange = ccxt.binance()
    symbol = "BTC/USDT"
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe="15m", limit=2880)  # ~30 days
    train_model(symbol, ohlcv)
