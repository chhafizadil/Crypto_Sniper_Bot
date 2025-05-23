# Utility functions for data validation and agreement checks.
# Changes:
# - Added calculate_agreement function to support 2/3 timeframe agreement logic.
# - Improved validation to handle edge cases.

import pandas as pd
from utils.logger import logger

# Validate DataFrame for required columns and data quality
def validate_dataframe(df: pd.DataFrame) -> bool:
    try:
        if df.empty or len(df) < 20:
            logger.warning("DataFrame is empty or too short")
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

# Calculate timeframe agreement for signals
def calculate_agreement(signals: list) -> tuple:
    try:
        if not signals:
            return None, 0
        directions = [s['direction'] for s in signals if s is not None]
        if not directions:
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
