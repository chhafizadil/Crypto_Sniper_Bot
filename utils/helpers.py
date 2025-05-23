# ڈیٹا تصدیق اور ایگریمنٹ چیک کے لیے یوٹیلیٹی فنکشنز۔
# تبدیلیاں:
# - 2/4 ایگریمنٹ کے لیے calculate_agreement فنکشن اپ ڈیٹ کیا۔

import pandas as pd
from utils.logger import logger

# ڈیٹا فریم کی تصدیق
def validate_dataframe(df: pd.DataFrame) -> bool:
    try:
        if df.empty or len(df) < 20:
            logger.warning("ڈیٹا فریم خالی یا بہت چھوٹا")
            return False
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            logger.warning(f"مطلوبہ کالم غائب: {required_columns}")
            return False
        if df[required_columns].isna().any().any():
            logger.warning("مطلوبہ کالموں میں NaN اقدار")
            return False
        logger.info("ڈیٹا فریم کامیابی سے تصدیق شدہ")
        return True
    except Exception as e:
        logger.error(f"ڈیٹا فریم تصدیق میں خرابی: {str(e)}")
        return False

# ٹائم فریم ایگریمنٹ کا حساب
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
        logger.info(f"ایگریمنٹ: {agreement_count}/{len(directions)} for {most_common_direction}")
        return most_common_direction, agreement_ratio * 100
    except Exception as e:
        logger.error(f"ایگریمنٹ حساب کرنے میں خرابی: {str(e)}")
        return None, 0
