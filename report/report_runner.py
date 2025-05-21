import pandas as pd
import os
import asyncio
from utils.logger import logger
from telebot.sender import send_telegram_signal
from datetime import datetime

async def generate_daily_summary():
    try:
        logger.info("Generating daily report...")
        csv_path = "logs/signals_log_new.csv"
        if not os.path.exists(csv_path):
            logger.warning("No signals log found at logs/signals_log_new.csv")
            return

        df = pd.read_csv(csv_path)
        if df.empty:
            logger.warning("Signals log is empty")
            return

        import pytz
        today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')

        today_signals = df[df['timestamp'].str.startswith(today)]
        
        if today_signals.empty:
            logger.info("No signals for today")
            message = "📊 *Daily Report*\n\nNo signals generated today."
        else:
            total_signals = len(today_signals)
            long_signals = len(today_signals[today_signals['direction'] == 'LONG'])
            short_signals = len(today_signals[today_signals['direction'] == 'SHORT'])
            avg_confidence = today_signals['confidence'].mean()
            
            message = (
                f"📊 *Daily Report ({today})*\n\n"
                f"📈 Total Signals: {total_signals}\n"
                f"↗️ Long Signals: {long_signals}\n"
                f"↘️ Short Signals: {short_signals}\n"
                f"🔍 Avg Confidence: {avg_confidence:.2f}%\n"
            )

        # Send report to Telegram
        signal = {
            "symbol": "REPORT",
            "direction": "N/A",
            "entry": 0,
            "tp1": 0,
            "tp2": 0,
            "tp3": 0,
            "sl": 0,
            "confidence": 0,
            "timeframe": "N/A",
            "trade_type": "Report",
            "timestamp": datetime.now(),
            "tp1_possibility": 0,
            "tp2_possibility": 0,
            "tp3_possibility": 0
        }
        await send_telegram_signal("REPORT", signal)
        logger.info("Daily report sent successfully")
    except Exception as e:
        logger.error(f"Error generating daily report: {str(e)}")
