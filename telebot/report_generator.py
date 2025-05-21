import pandas as pd
import os
from datetime import datetime, timedelta
from utils.logger import logger

async def generate_daily_summary():
    try:
        if not os.path.exists('logs/signals_log_new.csv'):
            logger.warning("No signal logs found for daily summary")
            return None
        
        df = pd.read_csv('logs/signals_log_new.csv')
        if df.empty:
            logger.warning("Signal log is empty")
            return None
            
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        
        daily_signals = df[df['timestamp'].dt.date == yesterday]
        if daily_signals.empty:
            logger.info("No signals for yesterday")
            return None
            
        total_signals = len(daily_signals)
        long_signals = len(daily_signals[daily_signals['direction'] == 'LONG'])
        short_signals = len(daily_signals[daily_signals['direction'] == 'SHORT'])
        avg_confidence = daily_signals['confidence'].mean()
        tp1_hit = len(daily_signals[daily_signals['status'] == 'tp1'])
        tp2_hit = len(daily_signals[daily_signals['status'] == 'tp2'])
        tp3_hit = len(daily_signals[daily_signals['status'] == 'tp3'])
        sl_hit = len(daily_signals[daily_signals['status'] == 'sl'])
        pending = len(daily_signals[daily_signals['status'] == 'pending'])
        
        summary = (
            f"📊 *Daily Signal Summary ({yesterday})*\n\n"
            f"Total Signals: {total_signals}\n"
            f"LONG Signals: {long_signals}\n"
            f"SHORT Signals: {short_signals}\n"
            f"Average Confidence: {avg_confidence:.2f}%\n"
            f"TP1 Hit: {tp1_hit}\n"
            f"TP2 Hit: {tp2_hit}\n"
            f"TP3 Hit: {tp3_hit}\n"
            f"SL Hit: {sl_hit}\n"
            f"Pending: {pending}\n"
        )
        
        logger.info(f"Daily summary generated for {yesterday}")
        return summary
    except Exception as e:
        logger.error(f"Error generating daily summary: {str(e)}")
        return None
