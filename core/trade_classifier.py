from utils.logger import logger

def classify_trade(confidence):
    try:
        if 80 <= confidence <= 100:
            return "Normal"
        else:
            return "Scalping"  # Default to Scalping
        logger.info(f"Trade classified with confidence {confidence:.2f}")
    except Exception as e:
        logger.error(f"Error classifying trade: {str(e)}")
        return "Scalping"
