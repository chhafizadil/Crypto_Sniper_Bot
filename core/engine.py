# سگنل جنریشن اور ٹیلیگرام نوٹیفکیشن کے لیے کور انجن۔
# تبدیلیاں:
# - تمام USDT جوڑوں کو اسکین کرنے کی منطق شامل کی۔
# - والیوم فلٹر کو $1,000,000 پر سیٹ کیا۔
# - 2/4 ایگریمنٹ کے ساتھ تجزیہ کیا۔

import asyncio
import ccxt.async_support as ccxt
from core.analysis import analyze_symbol_multi_timeframe
from utils.logger import logger
import pandas as pd
import psutil
from telegram import Bot
import os
from datetime import datetime
from dotenv import load_dotenv

logger.info("[Engine] فائل لوڈ ہوئی: core/engine.py")

load_dotenv()

# کور انجن چلائیں
async def run_engine():
    logger.info("[Engine] run_engine شروع")

    pid_file = "bot.pid"
    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            old_pid = int(f.read().strip())
        try:
            os.kill(old_pid, 0)
            logger.error("[Engine] دوسرا بوٹ چل رہا ہے۔ باہر نکل رہا ہوں۔")
            return
        except OSError:
            pass
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    try:
        required_vars = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "BINANCE_API_KEY", "BINANCE_API_SECRET"]
        for var in required_vars:
            if not os.getenv(var):
                logger.error(f"[Engine] ماحولیاتی متغیر غائب: {var}")
                return

        logs_dir = "logs"
        if not os.path.exists(logs_dir):
            logger.info(f"[Engine] لاگز ڈائریکٹری بنائی: {logs_dir}")
            os.makedirs(logs_dir)

        logger.info("[Engine] ٹیلیگرام بوٹ شروع")
        try:
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
            logger.info("[Engine] ٹیلیگرام بوٹ شروع ہوا")
        except Exception as e:
            logger.error(f"[Engine] ٹیلیگرام بوٹ شروع کرنے میں خرابی: {str(e)}")
            return

        logger.info("[Engine] Binance ایکسچینج شروع")
        try:
            exchange = ccxt.binance({
                "enableRateLimit": True,
                "apiKey": os.getenv("BINANCE_API_KEY"),
                "secret": os.getenv("BINANCE_API_SECRET")
            })
            logger.info("[Engine] Binance ایکسچینج شروع ہوا")
        except Exception as e:
            logger.error(f"[Engine] Binance ایکسچینج شروع کرنے میں خرابی: {str(e)}")
            return

        logger.info("[Engine] مارکیٹس لوڈ کر رہا ہوں")
        try:
            markets = await exchange.load_markets()
            symbols = [s for s in markets.keys() if s.endswith("/USDT")]
            logger.info(f"[Engine] {len(symbols)} USDT جوڑے ملے")
        except Exception as e:
            logger.error(f"[Engine] مارکیٹس لوڈ کرنے میں خرابی: {str(e)}")
            return

        last_signal_time = {}
        for symbol in symbols:
            memory_before = psutil.Process().memory_info().rss / 1024 / 1024
            cpu_percent = psutil.cpu_percent(interval=0.1)
            logger.info(f"[Engine] [{symbol}] تجزیہ سے پہلے - میموری: {memory_before:.2f} MB, CPU: {cpu_percent:.1f}%")

            if symbol in last_signal_time and (datetime.now(pytz.UTC) - last_signal_time[symbol]).total_seconds() < 14400:
                logger.info(f"[Engine] [{symbol}] کول ڈاؤن پر")
                continue

            try:
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', 0)
                if quote_volume_24h == 0 and base_volume > 0 and last_price > 0:
                    quote_volume_24h = base_volume * last_price
                if quote_volume_24h < 1000000:
                    logger.info(f"[Engine] [{symbol}] مسترد: کم والیوم (${quote_volume_24h:,.2f} < $1,000,000)")
                    continue
            except Exception as e:
                logger.error(f"[Engine] [{symbol}] ٹکر حاصل کرنے میں خرابی: {str(e)}")
                continue

            logger.info(f"[Engine] [{symbol}] سِمبل کا تجزیہ")
            try:
                signal = await analyze_symbol_multi_timeframe(symbol, exchange, ['15m', '1h', '4h', '1d'])
                if signal and signal["confidence"] >= 60 and signal["tp1_possibility"] >= 60:
                    message = (
                        f"🚨 {signal['symbol']} سگنل\n"
                        f"ٹائم فریم: {signal['timeframe']}\n"
                        f"سمت: {signal['direction']}\n"
                        f"قیمت: {signal['entry']:.2f}\n"
                        f"اعتماد: {signal['confidence']:.2f}%\n"
                        f"TP1: {signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)\n"
                        f"TP2: {signal['tp2']:.2f} ({signal['tp2_possibility']:.2f}%)\n"
                        f"TP3: {signal['tp3']:.2f} ({signal['tp3_possibility']:.2f}%)\n"
                        f"SL: {signal['sl']:.2f}\n"
                        f"شرائط: {', '.join(signal['conditions'])}"
                    )
                    logger.info(f"[Engine] [{symbol}] سگنل بنایا، ٹیلیگرام پر بھیج رہا ہوں")
                    try:
                        await bot.send_message(chat_id=os.getenv("TELEGRAM_CHAT_ID"), text=message)
                        logger.info(f"[Engine] [{symbol}] سگنل بھیجا: {signal['direction']}, اعتماد: {signal['confidence']:.2f}%")
                        last_signal_time[symbol] = datetime.now(pytz.UTC)
                    except Exception as e:
                        logger.error(f"[Engine] [{symbol}] ٹیلیگرام پیغام بھیجنے میں خرابی: {str(e)}")

                    signal_df = pd.DataFrame([signal])
                    logger.info(f"[Engine] [{symbol}] سگنل CSV میں محفوظ")
                    signal_df.to_csv(f"{logs_dir}/signals_log_new.csv", mode="a", header=not os.path.exists(f"{logs_dir}/signals_log_new.csv"), index=False)
                    logger.info(f"[Engine] [{symbol}] سگنل CSV میں محفوظ ہوا")
                else:
                    logger.info(f"[Engine] [{symbol}] کوئی درست سگنل نہیں (اعتماد: {signal['confidence'] if signal else 'None'}%)")
            except Exception as e:
                logger.error(f"[Engine] [{symbol}] سِمبل تجزیہ میں خرابی: {str(e)}")
                continue

            memory_after = psutil.Process().memory_info().rss / 1024 / 1024
            cpu_percent_after = psutil.cpu_percent(interval=0.1)
            memory_diff = memory_after - memory_before
            logger.info(f"[Engine] [{symbol}] تجزیہ کے بعد - میموری: {memory_after:.2f} MB (تبدیلی: {memory_diff:.2f} MB), CPU: {cpu_percent_after:.1f}%")

        logger.info("[Engine] ایکسچینج بند کر رہا ہوں")
        try:
            await exchange.close()
            logger.info("[Engine] ایکسچینج بند")
        except Exception as e:
            logger.error(f"[Engine] ایکسچینج بند کرنے میں خرابی: {str(e)}")

    except Exception as e:
        logger.error(f"[Engine] run_engine میں غیر متوقع خرابی: {str(e)}")
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)
