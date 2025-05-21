import pandas as pd
from utils.logger import logger  # Changed from 'log' to 'logger'

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
