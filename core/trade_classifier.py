from utils.logger import logger

def classify_trade(confidence):
    try:
        if confidence >= 85:
            trade_type = "Normal"
        else:
            trade_type = "Scalping"
        logger.info(f"Trade classified as {trade_type} with confidence {confidence:.2f}")
        return trade_type
    except Exception as e:
        logger.error(f"Error classifying trade: {str(e)}")
        return "Scalping"
