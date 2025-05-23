# Main entry point for the bot, orchestrating signal generation, Telegram integration, and health check.
# Changes:
# - Added /health endpoint for Koyeb health check on port 8000.
# - Replaced highest confidence signal selection with 2/3 timeframe agreement logic.
# - Added cooldown logic to prevent excessive processing.
# - Fixed datetime.utcnow() deprecation with datetime.now(UTC).
# - Optimized loop sleep to reduce Koyeb resource usage.

import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from datetime import datetime, timedelta, timezone
import telegram
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict, NetworkError, TelegramError
import os
import pytz
import requests
from dotenv import load_dotenv
from fastapi import FastAPI  # Added for health check endpoint

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
WEBHOOK_URL = "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook"
MIN_VOLUME = 1000000  # 1,000,000 USDT
COOLDOWN_SECONDS = 14400  # 4 hours cooldown per symbol

# Initialize FastAPI for health check endpoint
app = FastAPI()

# Health check endpoint for Koyeb to verify bot is running
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Analyze symbol across multiple timeframes and ensure 2/3 agreement
async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        # Check cooldown from signals.csv
        try:
            signals_df = pd.read_csv('logs/signals.csv')
            symbol_signals = signals_df[signals_df['symbol'] == symbol]
            if not symbol_signals.empty:
                last_signal_time = pd.to_datetime(symbol_signals['timestamp']).max()
                if (datetime.now(timezone.utc) - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
                    logger.info(f"[{symbol}] In cooldown, last signal at {last_signal_time}")
                    return None
        except FileNotFoundError:
            logger.warning("signals.csv not found, skipping cooldown check")

        # Analyze each timeframe
        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] Fetching OHLCV data for {timeframe}")
                df = await fetch_realtime_data(symbol, timeframe, limit=50)
                if df is None or len(df) < 30:
                    logger.warning(f"[{symbol}] Insufficient data for {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                logger.info(f"[{symbol}] OHLCV data fetched for {timeframe}: {len(df)} rows")
                signal = await predictor.predict_signal(symbol, df, timeframe)
                signals[timeframe] = signal
                logger.info(f"[{symbol}] Signal for {timeframe}: {signal}")
            except Exception as e:
                logger.error(f"[{symbol}] Error analyzing {timeframe}: {str(e)}")
                signals[timeframe] = None
                continue

        # Filter valid signals
        valid_signals = {t: s for t, s in signals.items() if s is not None}
        if len(valid_signals) < 2:
            logger.info(f"[{symbol}] Insufficient valid signals: {len(valid_signals)}/{len(timeframes)}")
            return None

        # Check for 2/3 timeframe agreement
        directions = [s['direction'] for s in valid_signals.values()]
        direction_counts = pd.Series(directions).value_counts()
        most_common_direction = direction_counts.idxmax() if not direction_counts.empty else None
        agreement_count = direction_counts.get(most_common_direction, 0) if most_common_direction else 0

        if agreement_count < 2:  # Require at least 2 timeframes to agree
            logger.info(f"[{symbol}] Insufficient timeframe agreement: {agreement_count}/{len(timeframes)} for {most_common_direction}")
            return None

        # Select signals with the agreed direction and calculate average confidence
        agreed_signals = [s for s in valid_signals.values() if s['direction'] == most_common_direction]
        final_signal = agreed_signals[0].copy()  # Use the first agreed signal as base
        final_signal['confidence'] = sum(s['confidence'] for s in agreed_signals) / len(agreed_signals)
        final_signal['timeframe'] = 'multi'  # Indicate multi-timeframe agreement
        final_signal['agreement'] = (agreement_count / len(timeframes)) * 100
        logger.info(f"[{symbol}] Selected signal with {agreement_count}/{len(timeframes)} agreement, confidence {final_signal['confidence']:.2f}%")

        # Volume check
        df = await fetch_realtime_data(symbol, agreed_signals[0]['timeframe'], limit=50)
        if df is None:
            logger.warning(f"[{symbol}] Failed to fetch data for volume check")
            return None

        latest = df.iloc[-1]
        if latest['quote_volume_24h'] < MIN_VOLUME:
            logger.info(f"[{symbol}] Signal rejected: Quote volume ${latest['quote_volume_24h']:,.2f} < ${MIN_VOLUME:,}")
            return None

        final_signal['timestamp'] = datetime.now(timezone.utc).isoformat() + 'Z'
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] Error in multi-timeframe analysis: {str(e)}")
        return None

# Convert UTC timestamp to Pakistan time
def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00'))
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Error converting timestamp: {str(e)}")
        return utc_timestamp_str

# Calculate TP probabilities (neutral to avoid bias)
def calculate_tp_probabilities(indicators):
    logger.info("Using dynamic TP probabilities based on indicators")
    base_prob = 50  # Neutral base probability
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "Bullish MACD" in indicators or "Bearish MACD" in indicators:
        base_prob += 10
    if "Strong Trend" in indicators:
        base_prob += 10
    if "Near Support" in indicators or "Near Resistance" in indicators:
        base_prob -= 5
    return {
        "TP1": min(base_prob, 80),  # Cap to avoid overconfidence
        "TP2": min(base_prob * 0.7, 60),
        "TP3": min(base_prob * 0.5, 40)
    }

# Determine leverage (balanced to avoid directional bias)
def determine_leverage(indicators):
    score = 0
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    # Positive signals
    if "Bullish MACD" in indicators or "Bearish MACD" in indicators:
        score += 2
    if "Strong Trend" in indicators:
        score += 2
    if "Above VWAP" in indicators or "Below VWAP" in indicators:
        score += 1
    # Negative signals
    if "Overbought Stochastic" in indicators or "Oversold Stochastic" in indicators:
        score -= 1
    return "40x" if score >= 5 else "30x" if score >= 3 else "20x" if score >= 1 else "10x"

# Fetch 24h volume from Binance API
def get_24h_volume(symbol):
    try:
        symbol_clean = symbol.replace("/", "").upper()
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_clean}"
        response = requests.get(url, timeout=5)
        data = response.json()
        quote_volume = float(data.get("quoteVolume", 0))
        return quote_volume, f"${quote_volume:,.2f}"
    except Exception as e:
        logger.error(f"Error fetching 24h volume for {symbol}: {str(e)}")
        return 0, "$0.00"

# Adjust TP levels for stablecoins
def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

# Send signal to Telegram
async def send_signal(signal):
    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            bot = telegram.Bot(token=BOT_TOKEN)
            conditions_str = ", ".join(signal.get('conditions', [])) or "None"
            
            volume, volume_str = get_24h_volume(signal['symbol'])
            if volume < MIN_VOLUME:
                logger.warning(f"Low volume for {signal['symbol']}: {volume_str}")
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
            logger.info(f"Attempting to send signal for {signal['symbol']} to Telegram (Attempt {attempt+1}/{max_retries})")
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
            logger.info(f"Signal successfully sent to Telegram: {signal['symbol']} - {signal['direction']}")
            return
        except NetworkError as ne:
            logger.error(f"Network error sending signal for {signal['symbol']}: {str(ne)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        except TelegramError as te:
            logger.error(f"Telegram error sending signal for {signal['symbol']}: {str(te)}")
            return
        except Exception as e:
            logger.error(f"Failed to send signal for {signal['symbol']}: {str(e)}")
            return
    logger.error(f"Failed to send signal for {signal['symbol']} after {max_retries} attempts")

# Main loop for continuous analysis
async def main_loop():
    exchange = ccxt.binance()
    symbols = ["ETH/USDT", "BNB/USDT", "NEO/USDT", "IOTA/USDT"]  # Reduced to high-volume coins
    timeframes = ["15m", "1h", "4h", "1d"]

    while True:
        for symbol in symbols:
            try:
                signal = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
                if signal:
                    await send_signal(signal)
                    logger.info(f"Processed signal for {symbol}: {signal}")
                else:
                    logger.info(f"No signal generated for {symbol}")
            except Exception as e:
                logger.error(f"Error processing {symbol}: {str(e)}")
        logger.info("Completed analysis cycle. Waiting 300 seconds...")
        await asyncio.sleep(300)  # Increased to reduce resource usage

# Initialize and start Telegram bot
async def start_bot():
    try:
        bot = telegram.Bot(token=BOT_TOKEN)
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Telegram webhook deleted successfully")
        except Exception as e:
            logger.warning(f"Error deleting webhook: {str(e)}")
        
        try:
            await bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook set to {WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"Error setting webhook: {str(e)}")
            raise

        # Test Telegram API
        try:
            await bot.send_message(chat_id=CHAT_ID, text="Bot initialized successfully!")
            logger.info("Test message sent to Telegram")
        except Exception as e:
            logger.error(f"Failed to send test message: {str(e)}")

        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Crypto Signal Bot is running!")))
        application.add_handler(CommandHandler("status", lambda u, c: u.message.reply_text("Bot is running.")))
        await application.initialize()
        await application.start()
        logger.info("Telegram webhook bot started successfully")
        return application
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
        raise

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    loop.create_task(main_loop())
    loop.run_forever()
