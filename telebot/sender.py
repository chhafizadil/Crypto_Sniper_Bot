# Telegram bot for sending signals and tracking trades
# Fixes:
# - Added missing json import
# - Fixed json.dumps syntax
# - Fixed bot.send_message syntax
# - Made Cloud Tasks optional with local tracking for Replit

import asyncio
import telegram
import pandas as pd
import json
import os
import ccxt.async_support as ccxt
from datetime import datetime
import pytz
import time
from utils.logger import logger
from dotenv import load_dotenv
try:
    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2
except ImportError:
    tasks_v2 = None
    duration_pb2 = None

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "crypto-sniper-bot")
QUEUE_NAME = "trade-tracking-queue"
LOCATION = "us-central1"

tasks_client = None
if tasks_v2:
    try:
        tasks_client = tasks_v2.CloudTasksClient()
    except Exception as e:
        logger.error(f"Cloud Tasks initialization failed: {str(e)}")

async def track_trade_local(symbol: str, signal: dict):
    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        direction = signal['direction']
        price = signal['entry']
        tp1 = signal['tp1']
        tp2 = signal['tp2']
        tp3 = signal['tp3']
        sl = signal['sl']
        status = "pending"

        for _ in range(720):  # 3 hours
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker.get('last', 0.0)
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
            await asyncio.sleep(15)

        logger.info(f"[{symbol}] Trade status: {status}")
        return status
    except Exception as e:
        logger.error(f"[{symbol}] Error tracking trade: {str(e)}")
        return "error"

async def track_trade(symbol: str, signal: dict):
    if tasks_client:
        try:
            parent = tasks_client.queue_path(PROJECT_ID, LOCATION, QUEUE_NAME)
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"https://{LOCATION}-{PROJECT_ID}.cloudfunctions.net/track_trade",
                    "body": json.dumps({"symbol": symbol, "signal": signal}).encode(),
                    "headers": {"Content-Type": "application/json"}
                },
                "schedule_time": None,
                "dispatch_deadline": duration_pb2.Duration(seconds=3600)
            }
            response = tasks_client.create_task(request={"parent": parent, "task": task})
            logger.info(f"[{symbol}] Trade tracking task created: {response.name}")
            return "pending"
        except Exception as e:
            logger.error(f"[{symbol}] Error creating tracking task: {str(e)}")
            return await track_trade_local(symbol, signal)
    else:
        return await track_trade_local(symbol, signal)

def update_signal_log(symbol: str, signal: dict, status: str):
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

async def send_signal(symbol: str, signal: dict, chat_id: str):
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
        logger.info(f"[{symbol}] Signal sent to Telegram")

        status = await track_trade(symbol, signal)
        update_signal_log(symbol, signal, status)
    except Exception as e:
        logger.error(f"[{symbol}] Failed to send signal: {str(e)}")
