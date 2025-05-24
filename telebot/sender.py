import asyncio
import telegram
from typing import Dict
from config.settings import TELEGRAM_BOT_TOKEN
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Maximum retries for sending a signal
MAX_RETRIES = 5  # Increased retries
# Base delay for retries (in seconds)
BASE_RETRY_DELAY = 10  # Increased delay
# Timeout for HTTP requests (in seconds)
TIMEOUT = 30

async def send_signal(symbol: str, signal: Dict, chat_id: str) -> None:
    """Send trading signal to Telegram with flood control handling."""
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

    # Format signal message
    message = (
        f"📊 *{symbol} - {signal['direction']}*\n"
        f"Entry: ${signal['entry']:.2f}\n"
        f"TP1: ${signal['tp1']:.2f} ({signal['tp1_possibility']:.1f}%)\n"
        f"TP2: ${signal['tp2']:.2f} ({signal['tp2_possibility']:.1f}%)\n"
        f"TP3: ${signal['tp3']:.2f} ({signal['tp3_possibility']:.1f}%)\n"
        f"SL: ${signal['sl']:.2f}\n"
        f"Leverage: {signal['leverage']}x\n"
        f"Confidence: {signal['confidence']:.1f}%\n"
        f"Timeframes: {signal['timeframes']}"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', timeout=TIMEOUT)
            logger.info(f"Signal sent successfully: {symbol} - {signal['direction']} ✔")
            await asyncio.sleep(3)  # 3 seconds delay between signals
            return

        except telegram.error.RateLimited as e:
            retry_after = getattr(e, 'retry_after', BASE_RETRY_DELAY)
            logger.error(f"Telegram error for {symbol}: Flood control exceeded. Retry in {retry_after} seconds")
            await asyncio.sleep(retry_after)

        except telegram.error.TimedOut:
            logger.error(f"Network error for {symbol}: Timed out")
            await asyncio.sleep(BASE_RETRY_DELAY)

        except Exception as e:
            logger.error(f"Error sending signal for {symbol}: {str(e)}")
            await asyncio.sleep(BASE_RETRY_DELAY)

        logger.info(f"Retrying in {BASE_RETRY_DELAY} seconds...")

    logger.error(f"Failed to send signal for {symbol} after {MAX_RETRIES} attempts")
