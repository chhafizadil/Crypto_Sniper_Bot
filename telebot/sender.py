# Updated telebot/sender.py to match requested signal format, add Trade Duration, and include daily report generation
import telegram
import asyncio
import pandas as pd
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict
from utils.logger import logger
from datetime import datetime, timedelta

# Hard-coded Telegram bot token and chat ID
BOT_TOKEN = "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU"
CHAT_ID = "-4694205383"

async def start(update, context):
    await update.message.reply_text("Crypto Signal Bot is running! Use /summary to get daily report.")

async def generate_daily_summary():
    try:
        file_path = 'logs/signals_log_new.csv'
        if not os.path.exists(file_path):
            logger.warning("Signals log file not found")
            return None

        df = pd.read_csv(file_path)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df_yesterday = df[df['timestamp'].dt.date == pd.to_datetime(yesterday).date()]

        if df_yesterday.empty:
            logger.info("No signals found for yesterday")
            return None

        total_signals = len(df_yesterday)
        successful_signals = len(df_yesterday[df_yesterday['status'] == 'successful'])
        failed_signals = len(df_yesterday[df_yesterday['status'] == 'failed'])
        pending_signals = len(df_yesterday[df_yesterday['status'] == 'pending'])

        successful_percentage = (successful_signals / total_signals * 100) if total_signals > 0 else 0
        failed_percentage = (failed_signals / total_signals * 100) if total_signals > 0 else 0
        pending_percentage = (pending_signals / total_signals * 100) if total_signals > 0 else 0

        top_signals = df_yesterday.sort_values(by='confidence', ascending=False).head(5)
        top_signals_text = ""
        for idx, row in top_signals.iterrows():
            conditions_str = ", ".join(eval(row['conditions']) if isinstance(row['conditions'], str) else row['conditions'])
            top_signals_text += (
                f"{idx + 1}. {row['symbol']} ({row['timeframe']}) - {row['direction']}\n"
                f"   - Confidence: {row['confidence']:.1f}%\n"
                f"   - Entry: ${row['entry']:.4f}\n"
                f"   - TP1: ${row['tp1']:.4f} ({row['tp1_possibility']:.1f}%)\n"
                f"   - TP2: ${row['tp2']:.4f} ({row['tp2_possibility']:.1f}%)\n"
                f"   - TP3: ${row['tp3']:.4f} ({row['tp3_possibility']:.1f}%)\n"
                f"   - SL: ${row['sl']:.4f}\n"
                f"   - Status: {row['status'].capitalize()}\n"
                f"   - Conditions: {conditions_str}\n"
            )

        report = (
            f"📊 *Daily Signal Report - {yesterday}*\n"
            f"🚀 Total Signals: {total_signals}\n"
            f"✅ Successful Signals: {successful_signals} ({successful_percentage:.1f}%)\n"
            f"❌ Failed Signals: {failed_signals} ({failed_percentage:.1f}%)\n"
            f"⏳ Pending Signals: {pending_signals} ({pending_percentage:.1f}%)\n\n"
            f"📈 Top Signals:\n{top_signals_text}"
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
        await update.message.reply_text("No signals available for yesterday.")

async def send_signal(signal):
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        conditions_str = ", ".join(signal.get('conditions', [])) or "None"
        message = (
            f"📈 *{signal['symbol']} Trading Signal*\n"
            f"📊 Direction: {signal['direction']}\n"
            f"⏰ Timeframe: {signal['timeframe']}\n"
            f"⏳ Trade Duration: {signal['trade_duration']}\n"
            f"💰 Entry Price: {signal['entry']:.4f}\n"
            f"🎯 TP1: {signal['tp1']:.4f} ({signal['tp1_possibility']:.1f}%)\n"
            f"🎯 TP2: {signal['tp2']:.4f} ({signal['tp2_possibility']:.1f}%)\n"
            f"🎯 TP3: {signal['tp3']:.4f} ({signal['tp3_possibility']:.1f}%)\n"
            f"🛑 SL: {signal['sl']:.4f}\n"
            f"🔍 Confidence: {signal['confidence']:.2f}%\n"
            f"⚡ Trade Type: {signal['trade_type']}\n"
            f"📈 Volume: ${signal['volume']:,.2f}\n"
            f"🔎 Conditions: {conditions_str}\n"
            f"🕒 Timestamp: {signal['timestamp']}"
        )
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
        logger.info(f"Signal sent to Telegram: {signal['symbol']} - {signal['direction']}")
    except Exception as e:
        logger.error(f"Error sending signal to Telegram: {str(e)}")

async def start_bot():
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram webhook deleted successfully")
        webhook_info = await bot.get_webhook_info()
        if not webhook_info.url:
            logger.info("Webhook confirmed deleted with no pending updates")
        for _ in range(5):
            try:
                await bot.get_updates(offset=-1, timeout=5)
                logger.info("Pending updates cleared via getUpdates")
                break
            except Conflict as e:
                logger.warning(f"Conflict while clearing updates: {str(e)}")
                await asyncio.sleep(3)
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("summary", summary))
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            poll_interval=4.0,
            timeout=15,
            error_callback=lambda e: logger.error(f"Polling error: {str(e)}")
        )
        logger.info("Telegram polling started successfully")
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
