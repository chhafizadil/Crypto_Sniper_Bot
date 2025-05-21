import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict
from utils.logger import logger
from datetime import datetime, timedelta
import os

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
WEBHOOK_URL = os.getenv('WEBHOOK_URL', "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook")

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
        latest_signal = df.iloc[-1]
        conditions_str = ", ".join(eval(latest_signal['conditions']) if isinstance(latest_signal['conditions'], str) else latest_signal['conditions'])
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
            f"⚖ Leverage: {latest_signal.get('leverage', 'N/A')}x\n"
            f"📈 Combined Candle Volume: ${latest_signal['volume']:,.2f}\n"
            f"📈 24h Volume: ${latest_signal.get('quote_volume_24h', 0):,.2f}\n"
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
            f"⚖ Leverage: {signal.get('leverage', 'N/A')}x\n"
            f"📈 Combined Candle Volume: ${signal['volume']:,.2f}\n"
            f"📈 24h Volume: ${signal.get('quote_volume_24h', 0):,.2f}\n"
            f"🔎 Indicators: {conditions_str}\n"
            f"🕒 Timestamp: {signal['timestamp']}"
        )
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        logger.info(f"Signal sent to Telegram: {signal['symbol']} - {signal['direction']}")
    except Exception as e:
        logger.error(f"Error sending signal to Telegram: {str(e)}")
        raise

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
