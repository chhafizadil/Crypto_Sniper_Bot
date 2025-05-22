import asyncio
import ccxt.async_support as ccxt
from core.analysis import analyze_symbol_multi_timeframe
from utils.logger import logger
import pandas as pd
import psutil
from telegram import Bot
import os
from dotenv import load_dotenv
import time

logger.info("[Engine] File loaded: core/engine.py")

load_dotenv()

async def run_engine():
    logger.info("[Engine] Starting run_engine")

    # Check for single bot instance
    pid_file = "bot.pid"
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            old_pid = int(f.read().strip())
        try:
            os.kill(old_pid, 0)
            logger.error("[Engine] Another bot instance is running. Exiting.")
            return
        except OSError:
            pass
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    try:
        required_vars = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "BINANCE_API_KEY", "BINANCE_API_SECRET"]
        for var in required_vars:
            if not os.getenv(var):
                logger.error(f"[Engine] Missing environment variable: {var}")
                return

        # Skip model check since it's not used
        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            logger.info(f"[Engine] Creating logs directory: {logs_dir}")
            os.makedirs(logs_dir)

        logger.info("[Engine] Initializing Telegram bot")
        try:
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
            logger.info("[Engine] Telegram bot initialized")
        except Exception as e:
            logger.error(f"[Engine] Error initializing Telegram bot: {str(e)}")
            return

        logger.info("[Engine] Initializing Binance exchange")
        try:
            exchange = ccxt.binance({
                "enableRateLimit": True,
                "apiKey": os.getenv("BINANCE_API_KEY"),
                "secret": os.getenv("BINANCE_API_SECRET")
            })
            logger.info("[Engine] Binance exchange initialized")
        except Exception as e:
            logger.error(f"[Engine] Error initializing Binance exchange: {str(e)}")
            return

        logger.info("[Engine] Loading markets")
        try:
            markets = await exchange.load_markets()
            symbols = [s for s in markets.keys() if s.endswith("/USDT")]
            logger.info(f"[Engine] Found {len(symbols)} USDT pairs")
        except Exception as e:
            logger.error(f"[Engine] Error loading markets: {str(e)}")
            return

        for symbol in symbols[:10]:  # Reduced from 15 to lower CPU usage
            memory_before = psutil.Process().memory_info().rss / 1024 / 1024
            cpu_percent = psutil.cpu_percent(interval=0.1)
            logger.info(f"[Engine] [{symbol}] Before analysis - Memory: {memory_before:.2f} MB, CPU: {cpu_percent:.1f}%")

            # Check volume
            try:
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume_24h = ticker.get('quoteVolume', 0)
                last_price = ticker.get('last', 0)
                if quote_volume_24h < 100000:
                    logger.info(f"[Engine] [{symbol}] Skipped: Low volume (${quote_volume_24h:,.2f} < $100,000) or price ({last_price})")
                    continue
            except Exception as e:
                logger.error(f"[Engine] [{symbol}] Error fetching ticker: {str(e)}")
                continue

            logger.info(f"[Engine] [{symbol}] Analyzing symbol")
            try:
                signal = await analyze_symbol_multi_timeframe(symbol, exchange, ['1h', '4h'])
                if signal and signal["confidence"] >= 65 and signal["tp1_possibility"] >= 65:  # Lowered from 70
                    message = (
                        f"🚨 {signal['symbol']} Signal\n"
                        f"Timeframe: {signal['timeframe']}\n"
                        f"Direction: {signal['direction']}\n"
                        f"Price: {signal['entry']:.2f}\n"
                        f"Confidence: {signal['confidence']:.2f}%\n"
                        f"TP1: {signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)\n"
                        f"TP2: {signal['tp2']:.2f} ({signal['tp2_possibility']:.2f}%)\n"
                        f"TP3: {signal['tp3']:.2f} ({signal['tp3_possibility']:.2f}%)\n"
                        f"SL: {signal['sl']:.2f}\n"
                        f"Conditions: {', '.join(signal['conditions'])}"
                    )
                    logger.info(f"[Engine] [{symbol}] Signal generated, sending to Telegram")
                    try:
                        await bot.send_message(chat_id=os.getenv("TELEGRAM_CHAT_ID"), text=message)
                        logger.info(f"[Engine] [{symbol}] Signal sent: {signal['direction']}, Confidence: {signal['confidence']:.2f}%")
                    except Exception as e:
                        logger.error(f"[Engine] [{symbol}] Error sending Telegram message: {str(e)}")

                    signal_df = pd.DataFrame([signal])
                    logger.info(f"[Engine] [{symbol}] Saving signal to CSV")
                    signal_df.to_csv(f"{logs_dir}/signals_log_new.csv", mode="a", header=not os.path.exists(f"{logs_dir}/signals_log_new.csv"), index=False)
                    logger.info(f"[Engine] [{symbol}] Signal saved to CSV")
                else:
                    logger.info(f"[Engine] [{symbol}] No valid signal (Confidence: {signal['confidence'] if signal else 'None'}%)")
            except Exception as e:
                logger.error(f"[Engine] [{symbol}] Error analyzing symbol: {str(e)}")
                continue

            memory_after = psutil.Process().memory_info().rss / 1024 / 1024
            cpu_percent_after = psutil.cpu_percent(interval=0.1)
            memory_diff = memory_after - memory_before
            logger.info(f"[Engine] [{symbol}] After analysis - Memory: {memory_after:.2f} MB (Change: {memory_diff:.2f} MB), CPU: {cpu_percent_after:.1f}%")

        logger.info("[Engine] Closing exchange")
        try:
            await exchange.close()
            logger.info("[Engine] Exchange closed")
        except Exception as e:
            logger.error(f"[Engine] Error closing exchange: {str(e)}")

    except Exception as e:
        logger.error(f"[Engine] Unexpected error in run_engine: {str(e)}")
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)
