# Logging configuration for the Crypto Signal Bot.
# Changes:
# - Removed Urdu from all logs and comments.
# - Optimized CSV logging for signals.
# - Added agreement details to signal logging.
# - Implemented log archiving for signals older than 7 days.

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pandas as pd
import pytz

# Ensure logs directory exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logger
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

# Log signal to CSV
def log_signal_to_csv(signal):
    try:
        csv_path = "logs/signals_log_new.csv"
        # Use PKT for timestamp
        timestamp = signal.get("timestamp", datetime.now(pytz.timezone("Asia/Karachi")).isoformat() + 'Z')
        timestamp = format_timestamp_to_pk(timestamp)  # Convert to PKT string
        data = pd.DataFrame({
            "symbol": [signal.get("symbol", "")],
            "price": [signal.get("entry", "")],
            "direction": [signal.get("direction", "")],
            "tp1": [signal.get("tp1", "")],
            "tp2": [signal.get("tp2", "")],
            "tp3": [signal.get("tp3", "")],
            "sl": [signal.get("sl", "")],
            "confidence": [signal.get("confidence", 0)],
            "trade_type": [signal.get("trade_type", "")],
            "timestamp": [timestamp],
            "tp1_possibility": [signal.get("tp1_possibility", 0)],
            "tp2_possibility": [signal.get("tp2_possibility", 0)],
            "tp3_possibility": [signal.get("tp3_possibility", 0)],
            "conditions": [", ".join(signal.get("conditions", []))],
            "volume": [signal.get("volume", 0)],
            "status": [signal.get("status", "pending")],
            "hit_timestamp": [signal.get("hit_timestamp", None)],
            "tp1_hit": [signal.get("tp1_hit", False)],
            "tp2_hit": [signal.get("tp2_hit", False)],
            "tp3_hit": [signal.get("tp3_hit", False)],
            "agreement": [signal.get("agreement", 0)]
        })

        # Append to existing CSV or create new
        if os.path.exists(csv_path):
            old_df = pd.read_csv(csv_path)
            if not data.empty:
                data = pd.concat([old_df, data], ignore_index=True)

        if not data.empty:
            data.to_csv(csv_path, index=False)
            logger.info(f"Signal logged to CSV for {signal.get('symbol', '')}")
        else:
            logger.error("No valid data to log to CSV")

        # Archive old logs
        archive_old_logs(csv_path)

    except Exception as e:
        logger.error(f"Error logging signal to CSV: {str(e)}")

# Archive logs older than 7 days
def archive_old_logs(csv_path):
    try:
        if not os.path.exists(csv_path):
            return
        df = pd.read_csv(csv_path)
        if df.empty:
            return

        current_date = datetime.now(pytz.timezone("Asia/Karachi"))
        week_ago = current_date - pd.Timedelta(days=7)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        old_data = df[df['timestamp'].dt.date < week_ago.date()]

        if not old_data.empty:
            archive_path = f"logs/archive/signals_log_{week_ago.strftime('%Y%m%d')}.csv"
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)
            old_data.to_csv(archive_path, index=False)
            new_data = df[df['timestamp'].dt.date >= week_ago.date()]
            new_data.to_csv(csv_path, index=False)
            logger.info(f"Archived {len(old_data)} old signals to {archive_path}")
    except Exception as e:
        logger.error(f"Error archiving logs: {str(e)}")

# Convert timestamp to PKT (for consistency with sender.py)
def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str
