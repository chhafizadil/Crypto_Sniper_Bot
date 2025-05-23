# ٹیلیگرام بوٹ انٹیگریشن سگنلز بھیجنے اور کمانڈز ہینڈل کرنے کے لیے۔
# تبدیلیاں:
# - بیچنگ ہٹائی، اصل سگنل سینڈنگ بحال کی۔
# - والیوم چیک کو $1,000,000 پر اپ ڈیٹ کیا۔
# - غیر جانبدار TP اور لیوریج منطق شامل کی۔

import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict, NetworkError, TelegramError
from utils.logger import logger
from datetime import datetime, timedelta
import os
import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
WEBHOOK_URL = "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook"
MIN_VOLUME = 1000000

# UTC ٹائم اسٹیمپ کو پاکستان ٹائم میں
def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00'))
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"ٹائم اسٹیمپ تبدیل کرنے میں خرابی: {str(e)}")
        return utc_timestamp_str

# TP امکانات (غیر جانبدار)
def calculate_tp_probabilities(indicators):
    logger.info("انڈیکیٹرز کی بنیاد پر متحرک TP امکانات")
    base_prob = 50
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:
        base_prob += 10
    if "Strong Trend" in indicators:
        base_prob += 10
    if "Near Support" in indicators or "Near Resistance" in indicators:
        base_prob -= 5
    return {
        "TP1": min(base_prob, 80),
        "TP2": min(base_prob * 0.7, 60),
        "TP3": min(base_prob * 0.5, 40)
    }

# لیوریج کا تعین (غیر جانبدار)
def determine_leverage(indicators):
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:
        score += 2
    if "Strong Trend" in indicators:
        score += 2
    if "VWAP" in indicators:
        score += 1
    if "Stochastic" in indicators:
        score -= 1
    return "40x" if score >= 5 else "30x" if score >= 3 else "20x" if score >= 1 else "10x"

# 24 گھنٹے کا والیوم
def get_24h_volume(symbol):
    try:
        symbol_clean = symbol.replace("/", "").upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}"
        response = requests.get(url, timeout=5)
        data = response.json()
        quote_volume = float(data.get("quoteVolume", 0))
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"{symbol} کے لیے 24 گھنٹے والیوم حاصل کرنے میں خرابی: {str(e)}")
        return 0, "$0.00"

# سٹیبل کوائن کے لیے TP
def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

# کمانڈ ہینڈلرز
async def start(update, context):
    await update.message.reply_text("Crypto Signal Bot چل رہا ہے! /summary, /report, /status, /signal, یا /help استعمال کریں۔")

async def help(update, context):
    help_text = (
        "📚 *Crypto Signal Bot کمانڈز*\n"
        "/start - بوٹ شروع\n"
        "/summary - آج کا سگنل خلاصہ\n"
        "/report - تفصیلی روزانہ ٹریڈنگ رپورٹ\n"
        "/status - بوٹ کی حالت\n"
        "/signal - تازہ سگنل\n"
        "/test - بوٹ کنیکٹیویٹی ٹیسٹ\n"
        "/help - یہ مدد پیغام"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def test(update, context):
    try:
        await update.message.reply_text("Crypto Signal Bot سے ٹیسٹ پیغام!")
        logger.info("ٹیسٹ پیغام کامیابی سے بھیجا")
    except Exception as e:
        logger.error(f"ٹیسٹ پیغام بھیجنے میں خرابی: {str(e)}")
        await update.message.reply_text(f"ٹیسٹ پیغام بھیجنے میں خرابی: {str(e)}")

async def status(update, context):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        bot_info = await bot.get_me()
        webhook_info = await bot.get_webhook_info()
        status_text = (
            f"🟢 بوٹ عام طور پر چل رہا ہے\n"
            f"🤖 بوٹ: @{bot_info.username}\n"
            f"🌐 ویب ہک: {webhook_info.url or 'سیٹ نہیں'}\n"
            f"📡 زیر التوا اپ ڈیٹس: {webhook_info.pending_update_count or 0}"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"حالت چیک کرنے میں خرابی: {str(e)}")
        await update.message.reply_text("🔴 بوٹ کی حالت چیک کرنے میں خرابی۔", parse_mode='Markdown')

async def signal(update, context):
    try:
        file_path = 'logs/signals.csv'
        if not os.path.exists(file_path):
            await update.message.reply_text("کوئی سگنلز دستیاب نہیں۔")
            return
        df = pd.read_csv(file_path)
        if df.empty:
            await update.message.reply_text("کوئی سگنلز دستیاب نہیں۔")
            return
        latest_signal = df.iloc[-1].to_dict()
        conditions_str = ", ".join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) and latest_signal['conditions'].startswith('[') else latest_signal['conditions'].split(", "))
        
        volume, volume_str = get_24h_volume(latest_signal['symbol'])
        if volume < MIN_VOLUME:
            logger.warning(f"{latest_signal['symbol']} کے لیے کم والیوم: {volume_str}")
            await update.message.reply_text("ناکافی سگنل والیوم۔")
            return

        probabilities = calculate_tp_probabilities(latest_signal['conditions'])
        latest_signal['tp1_possibility'] = probabilities['TP1']
        latest_signal['tp2_possibility'] = probabilities['TP2']
        latest_signal['tp3_possibility'] = probabilities['TP3']
        latest_signal['leverage'] = determine_leverage(latest_signal['conditions'])
        latest_signal['quote_volume_24h'] = volume_str
        latest_signal['timestamp'] = format_timestamp_to_pk(latest_signal['timestamp'])
        latest_signal['tp1'], latest_signal['tp2'], latest_signal['tp3'] = adjust_tp_for_stablecoin(
            latest_signal['symbol'], latest_signal['tp1'], latest_signal['tp2'], latest_signal['tp3'], latest_signal['entry']
        )

        message = (
            f"📈 *Trading Signal*\n"
            f"💱 Symbol: {latest_signal['symbol']}\n"
            f"📊 Direction: {latest_signal['direction']}\n"
            f"⏰ Timeframe: {latest_signal['timeframe']}\n"
            f"⏳ Duration: {latest_signal['trade_duration']}\n"
            f"💰 Entry: ${latest_signal['entry']:.2f}\n"
            f"🎯 TP1: ${latest_signal['tp1']:.2f} ({latest_signal['tp1_possibility']:.2f}%)\n"
            f"🎯 TP2: ${latest_signal['tp2']:.2f} ({latest_signal['tp2_possibility']:.2f}%)\n"
            f"🎯 TP3: ${latest_signal['tp3']:.2f} ({latest_signal['tp3_possibility']:.2f}%)\n"
            f"🛑 SL: ${latest_signal['sl']:.2f}\n"
            f"🔍 Confidence: {latest_signal['confidence']:.2f}%\n"
            f"⚡ Type: {latest_signal['trade_type']}\n"
            f"⚖ Leverage: {latest_signal.get('leverage', 'N/A')}\n"
            f"📈 Combined Candle Volume: ${latest_signal['volume']:,.2f}\n"
            f"📈 24h Volume: {latest_signal['quote_volume_24h']}\n"
            f"🔎 Indicators: {conditions_str}\n"
            f"🕒 Timestamp: {latest_signal['timestamp']}"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"تازہ سگنل حاصل کرنے میں خرابی: {str(e)}")
        await update.message.reply_text("تازہ سگنل حاصل کرنے میں خرابی۔")

# روزانہ خلاصہ رپورٹ
async def generate_daily_summary():
    try:
        file_path = 'logs/signals.csv'
        if not os.path.exists(file_path):
            logger.warning("سگنلز لاگ فائل نہیں ملی")
            return None
        df = pd.read_csv(file_path)
        today = datetime.now(pytz.timezone("Asia/Karachi")).date()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_today = df[df['timestamp'].dt.date == today]
        if df_today.empty:
            logger.info("آج کے لیے کوئی سگنلز نہیں ملے")
            return None
        total_signals = len(df_today)
        long_signals = len(df_today[df_today['direction'] == 'LONG'])
        short_signals = len(df_today[df_today['direction'] == 'SHORT'])
        successful_signals = len(df_today[df_today['status'] == 'successful'])
        failed_signals = len(df_today[df_today['status'] == 'failed'])
        pending_signals = len(df_today[df_today['status'] == 'pending'])
        successful_percentage = (successful_signals / total_signals * 100) if total_signals > 0 else 0
        avg_confidence = df_today['confidence'].mean() if total_signals > 0 else 0
        top_symbol = df_today['symbol'].mode()[0] if total_signals > 0 else "N/A"
        most_active_timeframe = df_today['timeframe'].mode()[0] if total_signals > 0 else "N/A"
        total_volume = df_today['volume'].sum() if total_signals > 0 else 0
        tp1_hits = len(df_today[df_today.get('tp1_hit', False) == True]) if 'tp1_hit' in df_today else 0
        tp2_hits = len(df_today[df_today.get('tp2_hit', False) == True]) if 'tp2_hit' in df_today else 0
        tp3_hits = len(df_today[df_today.get('tp3_hit', False) == True]) if 'tp3_hit' in df_today else 0
        sl_hits = len(df_today[df_today.get('sl_hit', False) == True]) if 'sl_hit' in df_today else 0
        report = (
            f"📊 *Daily Trading Summary ({today})*\n"
            f"📈 کل سگنلز: {total_signals}\n"
            f"🚀 لانگ سگنلز: {long_signals}\n"
            f"📉 شارٹ سگنلز: {short_signals}\n"
            f"🎯 کامیاب سگنلز: {successful_signals} ({successful_percentage:.2f}%)\n"
            f"🔍 اوسط اعتماد: {avg_confidence:.2f}%\n"
            f"🏆 ٹاپ سِمبل: {top_symbol}\n"
            f"📊 سب سے فعال ٹائم فریم: {most_active_timeframe}\n"
            f"⚡ کل تجزیہ شدہ والیوم: {total_volume:,.0f} (USDT)\n"
            f"🔎 سگنل اسٹیٹس بریک ڈاؤن:\n"
            f"   - TP1 ہٹ: {tp1_hits}\n"
            f"   - TP2 ہٹ: {tp2_hits}\n"
            f"   - TP3 ہٹ: {tp3_hits}\n"
            f"   - SL ہٹ: {sl_hits}\n"
            f"   - زیر التوا: {pending_signals}\n"
            f"بنایا گیا: {datetime.now(pytz.timezone('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        logger.info("روزانہ رپورٹ کامیابی سے بنائی")
        return report
    except Exception as e:
        logger.error(f"روزانہ رپورٹ بنانے میں خرابی: {str(e)}")
        return None

async def summary(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("آج کے لیے کوئی سگنلز نہیں۔")

async def report(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("آج کے لیے کوئی تفصیلی رپورٹ نہیں۔")

# سگنل بھیجیں
async def send_signal(signal):
    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            bot = telegram.Bot(token=BOT_TOKEN)
            conditions_str = ", ".join(signal.get('conditions', [])) or "None"
            
            volume, volume_str = get_24h_volume(signal['symbol'])
            if volume < MIN_VOLUME:
                logger.warning(f"{signal['symbol']} کے لیے کم والیوم: {volume_str}")
                return

            probabilities = calculate_tp_probabilities(signal.get('conditions', []))
            signal['tp1_possibility'] = probabilities['TP1']
            signal['tp2_possibility'] = probabilities['TP2']
            signal['tp3_possibility'] = probabilities['TP3']
            signal['leverage'] = determine_leverage(signal.get('conditions', []))
            signal['quote_volume_24h'] = volume_str
            signal['timestamp'] = format_timestamp_to_pk(signal['timestamp'])
            signal['tp1'], signal['tp2'], signal['tp3'] = adjust_tp_for_stablecoin(
                signal['symbol'], signal['tp1'], signal['tp2'], signal['tp3'], signal['entry']
            )

            message = (
                f"📈 *Trading Signal*\n"
                f"💱 Symbol: {signal['symbol']}\n"
                f"📊 Direction: {signal['direction']}\n"
                f"⏰ Timeframe: {signal['timeframe']}\n"
                f"⏳ Duration: {signal['trade_duration']}\n"
                f"💰 Entry: ${signal['entry']:.2f}\n"
                f"🎯 TP1: ${signal['tp1']:.2f} ({signal['tp1_possibility']:.2f}%)\n"
                f"🎯 TP2: ${signal['tp2']:.2f} ({signal['tp2_possibility']:.2f}%)\n"
                f"🎯 TP3: ${signal['tp3']:.2f} ({signal['tp3_possibility']:.2f}%)\n"
                f"🛑 SL: ${signal['sl']:.2f}\n"
                f"🔍 Confidence: {signal['confidence']:.2f}%\n"
                f"⚡ Type: {signal['trade_type']}\n"
                f"⚖ Leverage: {signal.get('leverage', 'N/A')}\n"
                f"📈 Combined Candle Volume: ${signal['volume']:,.2f}\n"
                f"📈 24h Volume: {signal['quote_volume_24h']}\n"
                f"🔎 Indicators: {conditions_str}\n"
                f"🕒 Timestamp: {signal['timestamp']}"
            )
            logger.info(f"{signal['symbol']} کے لیے سگنل ٹیلیگرام پر بھیجنے کی کوشش (کوشش {attempt+1}/{max_retries})")
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
            logger.info(f"سگنل کامیابی سے بھیجا: {signal['symbol']} - {signal['direction']}")
            return
        except NetworkError as ne:
            logger.error(f"{signal['symbol']} کے لیے نیٹ ورک خرابی: {str(ne)}")
            if attempt < max_retries - 1:
                logger.info(f"{retry_delay} سیکنڈ میں دوبارہ کوشش...")
                await asyncio.sleep(retry_delay)
        except TelegramError as te:
            logger.error(f"{signal['symbol']} کے لیے ٹیلیگرام خرابی: {str(te)}")
            return
        except Exception as e:
            logger.error(f"{signal['symbol']} کے لیے سگنل بھیجنے میں ناکامی: {str(e)}")
            return
    logger.error(f"{signal['symbol']} کے لیے {max_retries} کوششوں کے بعد سگنل ناکام")

# بوٹ شروع
async def start_bot():
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("ٹیلیگرام ویب ہک کامیابی سے ہٹایا")
        except Exception as e:
            logger.warning(f"ویب ہک ہٹانے میں خرابی: {str(e)}")
        
        try:
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"ویب ہک سیٹ: {WEBHOOK_URL}")
        except Conflict:
            logger.warning("ویب ہک تنازع، دوبارہ سیٹ کر رہا ہوں")
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"ویب ہک ری سیٹ: {WEBHOOK_URL}")

        try:
            await bot.send_message(chat_id=CHAT_ID, text="بوٹ کامیابی سے شروع!")
            logger.info("ٹیلیگرام پر ٹیسٹ پیغام بھیجا")
        except Exception as e:
            logger.error(f"ٹیسٹ پیغام بھیجنے میں ناکامی: {str(e)}")

        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("summary", summary))
        application.add_handler(CommandHandler("report", report))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("signal", signal))
        application.add_handler(CommandHandler("test", test))
        application.add_handler(CommandHandler("help", help))
        await application.initialize()
        await application.start()
        logger.info("ٹیلیگرام ویب ہک بوٹ کامیابی سے شروع")
        return application
    except Exception as e:
        logger.error(f"ٹیلیگرام بوٹ شروع کرنے میں خرابی: {str(e)}")
        raise
