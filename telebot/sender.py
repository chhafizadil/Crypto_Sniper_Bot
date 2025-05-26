import asyncio
import telegram
import logging
from utils.logger import logger
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Configure logging
logger = logging.getLogger(__name__)

async def send_signal(symbol: str, signal: dict, chat_id: str):
    "Send trading signal to Telegram chat."
    try:
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        message = (
            f"🔵 New Signal for {symbol}\n"
            f"Direction: {signal['direction']}\n"
            f"Entry: {signal['entry']}\n"
            f"TP1: {signal['tp1']}\n"
            f"TP2: {signal['tp2']}\n"
            f"TP3: {signal['tp3']}\n"
            f"SL: {signal['sl']}\n"
            f"Confidence: {signal['confidence']:.2f}%\n"
            f"Leverage: {signal.get('leverage', 'N/A')}\n"
            f"Timeframe: {signal.get('timeframe', 'N/A')}"
        )
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Signal sent successfully: {symbol} - {signal['direction']} ✔")
    except Exception as e:
        logger.error(f"Failed to send signal for {symbol}: {str(e)}")
