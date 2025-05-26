import pandas as pd
from typing import Dict, List
from core.indicators import calculate_indicators
from core.candle_patterns import detect_candle_patterns
from model.predictor import SignalPredictor
from utils.logger import logger
from utils.helpers import calculate_agreement

async def multi_timeframe_analysis(symbol: str, ohlcv_data: Dict[str, pd.DataFrame], timeframes: List[str]) -> Dict:
    """Perform multi-timeframe analysis with 2/4 agreement."""
    try:
        predictor = SignalPredictor()
        signals = {}

        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] Analyzing {timeframe}")
                df = ohlcv_data.get(timeframe)
                if df is None or len(df) < 30:
                    logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                # Ensure indicators are calculated
                df = calculate_indicators(df)
                if df is None:
                    logger.warning(f"[{symbol}] Failed to calculate indicators for {timeframe}")
                    signals[timeframe] = None
                    continue

                # Detect candle patterns
                candle_patterns = detect_candle_patterns(df)

                # Generate signal using predictor
                signal = await predictor.predict_signal(symbol, df, timeframe)
                if signal is None:
                    logger.info(f"[{symbol}] No signal generated for {timeframe}")
                    signals[timeframe] = None
                    continue

                # Add additional analysis
                latest = df.iloc[-1]
                signal['rsi'] = latest['rsi']
                signal['macd'] = {'macd': latest['macd'], 'signal': latest['macd_signal']}
                signal['vwap'] = latest['vwap']
                signal['candle_patterns'] = candle_patterns
                signals[timeframe] = signal
                logger.info(f"[{symbol}] Signal for {timeframe}: {signal['direction']}")
            except Exception as e:
                logger.error(f"[{symbol}] Error analyzing {timeframe}: {str(e)}")
                signals[timeframe] = None
                continue

        valid_signals = [s for s in signals.values() if s is not None]
        if len(valid_signals) < 2:
            logger.info(f"[{symbol}] Insufficient valid signals: {len(valid_signals)}/{len(timeframes)}")
            return None

        # Enforce 2/4 timeframe agreement
        direction, agreement = calculate_agreement(valid_signals)
        if agreement < 85:
            logger.info(f"[{symbol}] Insufficient timeframe agreement: {agreement:.2f}%")
            return None

        # Select signal with highest confidence
        agreed_signals = [s for s in valid_signals if s['direction'] == direction]
        final_signal = max(agreed_signals, key=lambda x: x['confidence'])
        final_signal['agreement'] = agreement
        final_signal['timeframe'] = 'multi'
        logger.info(f"[{symbol}] Final signal: {direction}, agreement: {agreement:.2f}%")
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None
