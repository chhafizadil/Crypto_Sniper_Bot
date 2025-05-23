import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict
from utils.logger import logger
from datetime import datetime, timedelta
import os
import pytz
import requests

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
WEBHOOK_URL = "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook"
MIN_VOLUME = 1000000  # $1M minimum 24h volume
MIN_AGREEMENT = 2  # At least 3/4 timeframe agreement

def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00'))
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

def calculate_tp_probabilities(indicators, historical_data=None):
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "Bullish MACD" in indicators: score += 2
    if "Strong Trend" in indicators: score += 2
    if "Overbought Stochastic" in indicators: score += 1
    if "Oversold Stochastic" in indicators: score += 1
    if "Above VWAP" in indicators: score += 1
    if "Hammer" in indicators: score += 1
    if "Near Support" in indicators: score += 2
    if "Near Resistance" in indicators: score -= 1

    if historical_data is None:
        if score >= 7:
            return {"TP1": 90, "TP2": 70, "TP3": 50}
        elif score >= 5:
            return {"TP1": 76, "TP2": 54, "TP3": 38}
        else:
            return {"TP1": 60, "TP2": 40, "TP3": 20}
    else:
        logger.info("Historical data TP probability calculation not implemented")
        return {"TP1": 60, "TP2": 40, "TP3": 20}

def determine_leverage(indicators):
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "Bullish MACD" in indicators: score += 2
    if "Strong Trend" in indicators: score += 2
    if "Above VWAP" in indicators: score += 1
    if "Near Support" in indicators: score += 1
    if "Near Resistance" in indicators: score -= 1
    if "Overbought Stochastic" in indicators: score -= 1
    if "Oversold Stochastic" in indicators: score -= 1

    if score >= 5:
        return "40x"
    elif score >= 3:
        return "30x"
    elif score >= 1:
        return "20x"
    else:
        return "10x"

def get_24h_volume(symbol):
    try:
        symbol_clean = symbol.replace("/", "").upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}"
        response = requests.get(url)
        data = response.json()
        quote_volume = float(data["quoteVolume"])
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching 24h volume for {symbol}: {str(e)}")
        return 0, "$0.00"

def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01  # 1% max for stablecoins
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

async def start(update, context):
    await update.message.reply_text("Crypto Signal Bot is running! Use /summary, /report, /status, /signal, or /help for more options.")

async def help(update, context):
    help_text = (
        "📚 *Crypto Signal Bot Commands*\n"
        "/start - Start the bot\n"
        "/summary - Get today's signal summary\n"
        "/report - Get detailed daily trading report\n"
        "/status - Check bot status\n"
        "/signal - Get the latest signal\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def status(update, context):
    await update.message.reply_text("🟢 Bot is running normally. Connected to Telegram and logging signals.", parse_mode='Markdown')

async def signal(update, context):
    try:
        file_path = 'logs/signals_log_new.csv'
        if not os.path.exists(file_path):
            await update.message.reply_text("No signals available.")
            return
        df = pd.read_csv(file_path)
        if df.empty:
            await update.message.reply_text("No signals available.")
            return
        latest_signal = df.iloc[-1].to_dict()
        conditions_str = ", ".join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) and latest_signal['conditions'].startswith('[') else latest_signal['conditions'].split(", "))
        
        # Validate volume and agreement
        volume, volume_str = get_24h_volume(latest_signal['symbol'])
        agreement = latest_signal.get('agreement', 0) / 100 * 3
        if volume < MIN_VOLUME:
            logger.warning(f"Low volume for {latest_signal['symbol']}: {volume_str}")
            await update.message.reply_text("Insufficient signal volume.")
            return
        if agreement < MIN_AGREEMENT:
            logger.warning(f"Insufficient timeframe agreement for {latest_signal['symbol']}: {agreement}/3")
            await update.message.reply_text("Insufficient timeframe agreement for signal.")
            return

        # Update dynamic fields
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
        logger.error(f"Error fetching latest signal: {str(e)}")
        await update.message.reply_text("Error fetching latest signal.")

async def generate_daily_summary():
    try:
        file_path = 'logs/signals_log_new.csv'
        if not os.path.exists(file_path):
            logger.warning("Signals log file not found")
            return None
        df = pd.read_csv(file_path)
        today = datetime.now().strftime('%Y-%m-%d')
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_today = df[df['timestamp'].dt.date == pd.to_datetime(today).date()]
        if df_today.empty:
            logger.info("No signals found for today")
            return None
        total_signals = len(df_today)
        long_signals = len(df_today[df_today['direction'] == 'Long'])
        short_signals = len(df_today[df_today['direction'] == 'Short'])
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
            f"📈 Total Signals: {total_signals}\n"
            f"🚀 Long Signals: {long_signals}\n"
            f"📉 Short Signals: {short_signals}\n"
            f"🎯 Successful Signals: {successful_signals} ({successful_percentage:.2f}%)\n"
            f"🔍 Average Confidence: {avg_confidence:.2f}%\n"
            f"🏆 Top Symbol: {top_symbol}\n"
            f"📊 Most Active Timeframe: {most_active_timeframe}\n"
            f"⚡ Total Volume Analyzed: {total_volume:,.0f} (USDT)\n"
            f"🔎 Signal Status Breakdown:\n"
            f"   - TP1 Hit: {tp1_hits}\n"
            f"   - TP2 Hit: {tp2_hits}\n"
            f"   - TP3 Hit: {tp3_hits}\n"
            f"   - SL Hit: {sl_hits}\n"
            f"   - Pending: {pending_signals}\n"
            f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        logger.info("Daily report generated successfully")
        return report
    except Exception as e:
        logger.error(f"Error generating daily report: {str(e)}")
        return None

async def summary(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("No signals available for today.")

async def report(update, context):
    report = await generate_daily_summary()
    if report:
        await update.message.reply_text(report, parse_mode='Markdown')
    else:
        await update.message.reply_text("No detailed report available for today.")

async def send_signal(signal):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        conditions_str = ", ".join(signal.get('conditions', [])) or "None"
        
        # Validate volume and agreement
        volume, volume_str = get_24h_volume(signal['symbol'])
        agreement = signal.get('agreement', 0) / 100 * 3
        if volume < MIN_VOLUME:
            logger.warning(f"Low volume for {signal['symbol']}: {volume_str}")
            return
        if agreement < MIN_AGREEMENT:
            logger.warning(f"Insufficient timeframe agreement for {signal['symbol']}: {agreement}/3")
            return

        # Update dynamic fields
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
        logger.info(f"Attempting to send signal for {signal['symbol']} to Telegram")
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        logger.info(f"Signal sent to Telegram: {signal['symbol']} - {signal['direction']}")
    except Exception as e:
        logger.error(f"Failed to send signal for {signal['symbol']}: {str(e)}")

async def start_bot():
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram webhook deleted successfully")
        await bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("summary", summary))
        application.add_handler(CommandHandler("report", report))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("signal", signal))
        application.add_handler(CommandHandler("help", help))
        await application.initialize()
        await application.start()
        logger.info("Telegram webhook bot started successfully")
        return application
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
        raise
