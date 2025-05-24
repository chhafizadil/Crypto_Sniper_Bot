from datetime import datetime
import time

def get_timestamp() -> float:
    """Get current timestamp in seconds."""
    return time.time()

def format_timestamp(timestamp: float) -> str:
    """Format timestamp to ISO format."""
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.isoformat()
    except Exception as e:
        # Fallback for invalid timestamp
        return datetime.now().isoformat()

def parse_timestamp(timestamp_str: str) -> float:
    """Parse ISO format timestamp to seconds."""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except ValueError as e:
        # Handle invalid isoformat string
        return time.time()
