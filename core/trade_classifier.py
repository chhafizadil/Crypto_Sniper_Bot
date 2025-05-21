# Updated core/trade_classifier.py to remove Trade Type: None and set default to Scalping
def classify_trade(confidence):
    if confidence >= 75:
        return "Swing"
    elif 60 <= confidence < 75:
        return "Normal"
    else:
        return "Scalping"  # Default to Scalping
