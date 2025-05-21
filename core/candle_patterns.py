import pandas as pd
from utils.logger import logger

def is_bullish_engulfing(df):
    try:
        if len(df) < 2:
            return [False] * len(df)
        prev_candle = df.shift(1)
        conditions = (
            (prev_candle['close'] < prev_candle['open']) &
            (df['close'] > df['open']) &
            (df['open'] <= prev_candle['close']) &
            (df['close'] >= prev_candle['open'])
        )
        logger.info("Bullish engulfing pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_bullish_engulfing: {str(e)}")
        return [False] * len(df)

def is_bearish_engulfing(df):
    try:
        if len(df) < 2:
            return [False] * len(df)
        prev_candle = df.shift(1)
        conditions = (
            (prev_candle['close'] > prev_candle['open']) &
            (df['close'] < df['open']) &
            (df['open'] >= prev_candle['close']) &
            (df['close'] <= prev_candle['open'])
        )
        logger.info("Bearish engulfing pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_bearish_engulfing: {str(e)}")
        return [False] * len(df)

def is_doji(df):
    try:
        body = abs(df['close'] - df['open'])
        range_candle = df['high'] - df['low']
        conditions = (body <= range_candle * 0.1) & (range_candle > 0)
        logger.info("Doji pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_doji: {str(e)}")
        return [False] * len(df)

def is_hammer(df):
    try:
        body = abs(df['close'] - df['open'])
        lower_shadow = df['open'].where(df['close'] >= df['open'], df['close']) - df['low']
        upper_shadow = df['high'] - df['close'].where(df['close'] >= df['open'], df['open'])
        range_candle = df['high'] - df['low']
        conditions = (
            (lower_shadow >= 2 * body) &
            (upper_shadow <= body * 0.5) &
            (range_candle > 0)
        )
        logger.info("Hammer pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_hammer: {str(e)}")
        return [False] * len(df)

def is_shooting_star(df):
    try:
        body = abs(df['close'] - df['open'])
        upper_shadow = df['high'] - df['close'].where(df['close'] >= df['open'], df['open'])
        lower_shadow = df['open'].where(df['close'] >= df['open'], df['close']) - df['low']
        range_candle = df['high'] - df['low']
        conditions = (
            (upper_shadow >= 2 * body) &
            (lower_shadow <= body * 0.5) &
            (range_candle > 0)
        )
        logger.info("Shooting star pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_shooting_star: {str(e)}")
        return [False] * len(df)

def is_three_white_soldiers(df):
    try:
        if len(df) < 3:
            return [False] * len(df)
        candle_1 = df.shift(2)
        candle_2 = df.shift(1)
        conditions = (
            (candle_1['close'] > candle_1['open']) &
            (candle_2['close'] > candle_2['open']) &
            (df['close'] > df['open']) &
            (candle_2['close'] > candle_1['close']) &
            (df['close'] > candle_2['close']) &
            (candle_2['open'] > candle_1['open']) &
            (df['open'] > candle_2['open'])
        )
        logger.info("Three white soldiers pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_three_white_soldiers: {str(e)}")
        return [False] * len(df)

def is_three_black_crows(df):
    try:
        if len(df) < 3:
            return [False] * len(df)
        candle_1 = df.shift(2)
        candle_2 = df.shift(1)
        conditions = (
            (candle_1['close'] < candle_1['open']) &
            (candle_2['close'] < candle_2['open']) &
            (df['close'] < df['open']) &
            (candle_2['close'] < candle_1['close']) &
            (df['close'] < candle_2['close']) &
            (candle_2['open'] < candle_1['open']) &
            (df['open'] < candle_2['open'])
        )
        logger.info("Three black crows pattern calculated")
        return conditions
    except Exception as e:
        logger.error(f"Error in is_three_black_crows: {str(e)}")
        return [False] * len(df)
