# Daily report generation
# Merged from: report_runner.py
# Changes:
# - Consolidated daily summary generation
# - Added ML signal performance metrics
# - Ensured async compatibility with sender.py

import pandas as pd
import os
from datetime import datetime, timedelta
import asyncio
from utils.logger import logger
from telebot.sender import send_signal

# Generate daily summary for Telegram report
async def generate_daily_summary():
    # Generate daily summary of trading signals
    try:
        csv_path = 'logs/signals_log.csv'
        if not os.path.exists(csv_path):
            logger.warning("No signals log found")
            return None

        df = pd.read_csv(csv_path)
        if df.empty:
            logger.warning("Empty signals log")
            return None

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        daily_signals = df[df['timestamp'].dt.date == yesterday]
        if daily_signals.empty:
            logger.info(f"No signals for {yesterday}")
            return None

        # Calculate summary metrics
        total_signals = len(daily_signals)
        long_signals = len(daily_signals[daily_signals['direction'] == 'LONG'])
        short_signals = len(daily_signals[daily_signals['direction'] == 'SHORT'])
        avg_confidence = daily_signals['confidence'].mean()
        tp1_hit = len(daily_signals[daily_signals['status'] == 'tp1'])
        tp2_hit = len(daily_signals[daily_signals['status'] == 'tp2'])
        tp3_hit = len(daily_signals[daily_signals['status'] == 'tp3'])
        sl_hit = len(daily_signals[daily_signals['status'] == 'sl'])
        pending = len(daily_signals[daily_signals['status'] == 'pending'])

        # Prepare summary message
        summary = (
            f"📊 *Daily Signal Summary ({yesterday})*\n\n"
            f"Total Signals: {total_signals}\n"
            f"Long Signals: {long_signals}\n"
            f"Short Signals: {short_signals}\n"
            f"Average Confidence: {avg_confidence:.2f}%\n"
            f"TP1 Hit: {tp1_hit}\n"
            f"TP2 Hit: {tp2_hit}\n"
            f"TP3 Hit: {tp3_hit}\n"
            f"SL Hit: {sl_hit}\n"
            f"Pending: {pending}\n"
        )

        # Send summary to Telegram
        signal = {
            "symbol": "REPORT",
            "direction": "N/A",
            "entry": 0.0,
            "tp1": 0.0,
            "tp2": 0.0,
            "tp3": 0.0,
            "sl": 0.0,
            "confidence": 0.0,
            "timeframe": "N/A",
            "trade_type": "Report",
            "timestamp": datetime.now().isoformat(),
            "tp1_possibility": 0.0,
            "tp2_possibility": 0.0,
            "tp3_possibility": 0.0
        }
        await send_signal("REPORT", signal, "Report")
        logger.info(f"Daily summary generated and sent for {yesterday}")
        return summary
    except Exception as e:
        logger.error(f"Error generating daily summary: {str(e)}")
        return None
