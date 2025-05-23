# Utility functions for data validation and agreement checks.
# Changes:
# - Removed Urdu from all logs and comments.
# - Updated calculate_agreement for 2/4 timeframe agreement.
# - Added PKT timestamp handling.

import pandas as pd
from utils.logger import logger
from datetime import datetime
import pytz

# Validate DataFrame
def validate_dataframe(df: pd.DataFrame) -> bool:
    try:
        if df.empty or len(df) < 20:
            logger.warning("DataFrame is empty or too small")
            return False
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            logger.warning(f"Missing required columns: {required_columns}")
            return False
        if df[required_columns].isna().any().any():
            logger.warning("NaN values in required columns")
            return False
        logger.info("DataFrame validated successfully")
        return True
    except Exception as e:
        logger.error(f"Error validating DataFrame: {str(e)}")
        return False

# Calculate timeframe agreement
def calculate_agreement(signals: list) -> tuple:
    try:
        if not signals:
            logger.warning("No signals provided for agreement calculation")
            return None, 0
        directions = [s['direction'] for s in signals if s is not None]
        if not directions:
            logger.warning("No valid directions found in signals")
            return None, 0
        direction_counts = pd.Series(directions).value_counts()
        most_common_direction = direction_counts.idxmax()
        agreement_count = direction_counts.get(most_common_direction, 0)
        agreement_ratio = agreement_count / len(directions)
        logger.info(f"Agreement: {agreement_count}/{len(directions)} for {most_common_direction}")
        return most_common_direction, agreement_ratio * 100
    except Exception as e:
        logger.error(f"Error calculating agreement: {str(e)}")
        return None, 0

# Convert timestamp to PKT
def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00').split('+00:00+')[0])
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str
