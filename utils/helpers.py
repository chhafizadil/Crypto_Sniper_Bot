from datetime import datetime
import time
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_timestamp() -> float:
    """Get current timestamp in seconds."""
    return time.time()

def format_timestamp(timestamp: float) -> str:
    """Format timestamp to ISO format."""
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.isoformat()
    except Exception as e:
        logger.error(f"Error formatting timestamp: {str(e)}")
        return datetime.now().isoformat()

def parse_timestamp(timestamp_str: str) -> float:
    """Parse timestamp to seconds, handling multiple formats."""
    try:
        # Try ISO format
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except ValueError:
        try:
            # Try custom format: '24 May 2025, 12:23 PM'
            dt = datetime.strptime(timestamp_str, '%d %b %Y, %I:%M %p')
            return dt.timestamp()
        except ValueError as e:
            logger.error(f"Invalid timestamp format: {timestamp_str}, using current time")
            return time.time()
