# Main script to run the trading bot
# Aligned with merged files (indicators.py, predictor.py, sender.py, report_generator.py, trainer.py)
# Changes:
# - Updated imports to use merged modules
# - Ensured real-time Binance data via collector.py
# - Integrated ML predictions from predictor.py
# - Error handling for robust execution

import asyncio
import os
from dotenv import load_dotenv
from core.engine import TradingEngine
from utils.logger import logger
from telebot.report_generator import generate_daily_summary
import ccxt.async_support as ccxt

# Load environment variables
load_dotenv()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

async def main():
    # Initialize and run the trading bot
    try:
        logger.info("Starting trading bot")

        # Initialize Binance exchange
        exchange = ccxt.binance({
            'apiKey': BINANCE_API_KEY,
            'secret': BINANCE_API_SECRET,
            'enableRateLimit': True,
        })

        # Initialize trading engine
        engine = TradingEngine(exchange)
        
        # Run tasks concurrently
        tasks = [
            engine.run(),
            generate_daily_summary()  # Daily report generation
        ]
        await asyncio.gather(*tasks)
        
        # Close exchange connection
        await exchange.close()
        logger.info("Trading bot stopped")
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        await exchange.close()

if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())
