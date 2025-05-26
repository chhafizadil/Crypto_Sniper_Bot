# Telegram bot for sending signals and tracking trades
# Merged from: tracker.py
# Changes:
# - Integrated trade tracking from tracker.py
# - Added signal status updates to CSV log
# - Ensured async compatibility with Binance real-time data

import asyncio
import telegram
import pandas as pd
from utils.logger import logger
from dotenv import load_dotenv
import os
import ccxt.async_support as ccxt
from datetime import datetime
import pytz

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Track trade status (from tracker.py)
async def track_trade(symbol: str, signal: dict):
    # Track trade status (TP1/TP2/TP3/SL) for up to 3 hours
    try:
        exchange = ccxt.binance({
            'enableRateLimit': True
        })
        direction = signal["direction"]
        price = signal["entry"]
        tp1 = signal["tp1"]
        tp2 = signal["tp2"]
        tp3 = signal["tp3"]
        sl = signal["sl"]

        status = "pending"
        for _ in range(720):  # Check for ~3 hours (720 * 15s)
            try:
                ticker = await exchange.fetch_ticker(symbol)
                current_price = ticker.get("last", 0.0)

                if direction == "LONG":
                    if current_price >= tp3:
                        status = "tp3"
                        break
                    elif current_price >= tp2:
                        status = "tp2"
                    elif current_price >= tp1:
                        status = "tp1"
                    elif current_price <= sl:
                        status = "sl"
                        break
                else:
                    if current_price <= tp3:
                        status = "tp3"
                        break
                    elif current_price <= tp2:
                        status = "tp2"
                    elif current_price <= tp1:
                        status = "tp1"
                    elif current_price >= sl:
                        status = "sl"
                        break
            except Exception as e:
                logger.error(f"[{symbol}] Error fetching ticker: {str(e)}")
                continue

            await asyncio.sleep(1)  # Check every 15 seconds

        logger.info(f"[{symbol}] Trade status: {status}")
        update_signal_status(symbol, signal, status)
        await exchange.close()
        return status
    except Exception as e:
        logger.error(f"[{symbol}] Error tracking trade: {str(e)}")
        await exchange.close()
        return "error"

# Update signals log CSV (from tracker.py)
def update_signal_log(symbol: str, signal: dict, status: str):
    # Update signal status in signals_log.csv
    try:
        csv_path = "logs/signals_log.csv"
        data = pd.DataFrame({
            "timestamp": [signal.get("timestamp", datetime.now(pytz.UTC).isoformat())],
            "symbol": [symbol],
            "direction": [signal.get("direction", "")],
            "entry_price": [signal.get("entry", 0.0)],
            "tp1": [signal.get("tp1", 0.0)],
            "tp2": [signal.get("tp2", 0.0)],
            "tp3": [signal.get("tp3", 0.0)],
            "sl": [signal.get("sl", 0.0)],
            "confidence": [signal.get("confidence", 0.0)],
            "trade_type": [signal.get("trade_type", "Normal")],
            "status": [status]
        })

        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            df = pd.concat([df, data], ignore_index=True)
        else:
            df = data

        df.to_csv(csv_path, index=False)
        logger.info(f"[{symbol}] Signal log updated with status: {status}")
    except Exception as e:
        logger.error(f"[{symbol}] Error updating signal log: {str(e)}")

# Send signal to Telegram
async def send_signal(symbol: str, signal: dict, chat_id: str):
    # Send trading signal to Telegram chat
    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        message = (
            f"🔵 New Signal for {symbol}\n\n"
            f"Direction: {signal['direction']}\n"
            f"Entry: ${signal['entry']:.2f}\n"
            f"TP1: ${signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)\n"
            f"TP2: ${signal['tp2']:.2f} ({signal['tp2_possibility']:.2f}%)\n"
            f"TP3: ${signal['tp3']:.2f} ({signal['tp3_possibility']:.2f}%)\n"
            f"SL: ${signal['sl']:.2f}\n"
            f"Confidence: {signal['confidence']:.2f}%\n"
            f"Timeframe: {signal.get('timeframe', 'N/A')}\n"
            f"Trade Type: {signal.get('trade_type', 'N/A')}"
        )
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Signal sent successfully: {symbol} - {signal['direction']}")

        # Start tracking trade status
        asyncio.create_task(track_trade(symbol, signal))
    except Exception as e:
        logger.error(f"Failed to send signal for {symbol}: {str(e)}")
