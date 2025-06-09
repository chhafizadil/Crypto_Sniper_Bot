# Utility functions for timestamp handling and scanning
# Changes:
# - Added scan_pause function for 5-minute pause
# - Added is_cooldown_active for 4-hour cooldown check
# - Optimized logging for Cloud Run

from datetime import datetime
import time
import asyncio
import logging
from utils.logger import logger

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_timestamp() -> float:
    # Get current timestamp in seconds
    return time.time()

def format_timestamp(timestamp: float) -> str:
    # Format timestamp to ISO format
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.isoformat()
    except Exception as e:
        logger.error(f"Error formatting timestamp: {str(e)}")
        return datetime.now().isoformat()

def parse_timestamp(timestamp_str: str) -> float:
    # Parse timestamp to seconds, handling multiple formats
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except ValueError:
        try:
            dt = datetime.strptime(timestamp_str, '%d %b %Y, %I:%M %p')
            return dt.timestamp()
        except ValueError as e:
            logger.error(f"Invalid timestamp format: {timestamp_str}, using current time")
            return time.time()

async def scan_pause(seconds: int):
    # Pause scanning for specified seconds
    try:
        logger.info(f"Pausing scan for {seconds} seconds")
        await asyncio.sleep(seconds)
        logger.info("Scan pause completed")
    except Exception as e:
        logger.error(f"Error in scan pause: {str(e)}")

def is_cooldown_active(symbol: str, last_signal_time: dict, cooldown: int) -> bool:
    # Check if symbol is in 4-hour cooldown
    try:
        if symbol in last_signal_time:
            current_time = datetime.now()
            time_diff = (current_time - last_signal_time[symbol]).total_seconds()
            if time_diff < cooldown:
                logger.info(f"[{symbol}] Cooldown active, {int((cooldown - time_diff)/60)} minutes remaining")
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking cooldown for {symbol}: {str(e)}")
        return False
