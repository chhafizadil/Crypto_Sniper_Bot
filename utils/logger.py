# Logging configuration for the Crypto Signal Bot
# Changes:
# - Moved signals_log.csv to in-memory storage for Cloud Run
# - Integrated with Cloud Logging
# - Updated log_signal_to_csv to store in memory
# - Removed archiving due to in-memory logging

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pandas as pd
import pytz

# Ensure logs directory exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logger for Cloud Run
log_formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

log_file = os.path.join(LOG_DIR, "bot.log")
file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger("crypto-signal-bot")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.propagate = False

# In-memory signals log for Cloud Run
signals_data = []

def log_signal_to_csv(signal):
    # Log signal to in-memory DataFrame
    try:
        global signals_data
        timestamp = signal.get("timestamp", datetime.now(pytz.timezone("Asia/Karachi")).isoformat() + 'Z')
        timestamp = format_timestamp_to_pk(timestamp)
        data = {
            "symbol": signal.get("symbol", ""),
            "price": signal.get("entry", ""),
            "direction": signal.get("direction", ""),
            "tp1": signal.get("tp1", ""),
            "tp2": signal.get("tp2", ""),
            "tp3": signal.get("tp3", ""),
            "sl": signal.get("sl", ""),
            "confidence": signal.get("confidence", 0),
            "trade_type": signal.get("trade_type", ""),
            "timestamp": timestamp,
            "tp1_possibility": signal.get("tp1_possibility", 0),
            "tp2_possibility": signal.get("tp2_possibility", 0),
            "tp3_possibility": signal.get("tp3_possibility", 0),
            "conditions": ", ".join(signal.get("conditions", [])),
            "volume": signal.get("volume", 0),
            "status": signal.get("status", "pending"),
            "hit_timestamp": signal.get("hit_timestamp", None),
            "tp1_hit": signal.get("tp1_hit", False),
            "tp2_hit": signal.get("tp2_hit", False),
            "tp3_hit": signal.get("tp3_hit", False),
            "agreement": signal.get("agreement", 0),
            "tp1_profit_pct": signal.get("tp1_profit_pct", 0),  # Added profit percentage
            "tp2_profit_pct": signal.get("tp2_profit_pct", 0),  # Added profit percentage
            "tp3_profit_pct": signal.get("tp3_profit_pct", 0)   # Added profit percentage
        }

        signals_data.append(data)
        logger.info(f"Signal logged to in-memory for {signal.get('symbol', '')}")
    except Exception as e:
        logger.error(f"Error logging signal to in-memory: {str(e)}")

def format_timestamp_to_pk(utc_timestamp_str):
    # Convert timestamp to PKT
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str
