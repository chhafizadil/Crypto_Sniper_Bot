# مین انٹری پوائنٹ، سگنل جنریشن، ٹیلیگرام انٹیگریشن، اور ہیلتھ چیک کو منظم کرتا ہے۔
# تبدیلیاں:
# - تمام USDT جوڑوں کو اسکین کرنے کی منطق شامل کی۔
# - والیوم تھریش ہولڈ کو $1,000,000 پر سیٹ کیا۔
# - 2/4 ٹائم فریم ایگریمنٹ نافذ کیا۔
# - ہیلتھ چیک کے لیے FastAPI درست کیا۔
# - pytz.UTC کا استعمال کیا۔

import pandas as pd
import asyncio
import ccxt.async_support as ccxt
from model.predictor import SignalPredictor
from data.collector import fetch_realtime_data
from utils.logger import logger
from datetime import datetime, timedelta
import telegram
from telegram.ext import Application, CommandHandler
from telegram.error import Conflict, NetworkError, TelegramError
import os
import pytz
import requests
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "7620836100:AAGY7xBjNJMKlzrDDMrQ5hblXzd_k_BvEtU")
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', "-4694205383")
WEBHOOK_URL = "https://willowy-zorina-individual-personal-384d3443.koyeb.app/webhook"
MIN_VOLUME = 1000000  # 1,000,000 USDT
COOLDOWN_SECONDS = 14400  # 4 گھنٹے کول ڈاؤن

# FastAPI ہیلتھ چیک کے لیے
app = FastAPI()

# Koyeb ہیلتھ چیک اینڈ پوائنٹ
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# ملٹی ٹائم فریم تجزیہ اور 2/4 ایگریمنٹ چیک
async def analyze_symbol_multi_timeframe(symbol: str, exchange: ccxt.Exchange, timeframes: list) -> dict:
    try:
        predictor = SignalPredictor()
        signals = {}

        # کول ڈاؤن چیک
        try:
            signals_df = pd.read_csv('logs/signals.csv')
            symbol_signals = signals_df[signals_df['symbol'] == symbol]
            if not symbol_signals.empty:
                last_signal_time = pd.to_datetime(symbol_signals['timestamp']).max()
                if (datetime.now(pytz.UTC) - last_signal_time).total_seconds() < COOLDOWN_SECONDS:
                    logger.info(f"[{symbol}] کول ڈاؤن میں، آخری سگنل: {last_signal_time}")
                    return None
        except FileNotFoundError:
            logger.warning("signals.csv نہیں ملی، کول ڈاؤن چیک چھوڑ رہا ہوں")

        # ہر ٹائم فریم کا تجزیہ
        for timeframe in timeframes:
            try:
                logger.info(f"[{symbol}] {timeframe} کے لیے OHLCV ڈیٹا حاصل کر رہا ہے")
                df = await fetch_realtime_data(symbol, timeframe, limit=50)
                if df is None or len(df) < 30:
                    logger.warning(f"[{symbol}] ناکافی ڈیٹا {timeframe}: {len(df) if df is not None else 'None'}")
                    signals[timeframe] = None
                    continue

                logger.info(f"[{symbol}] {timeframe} کے لیے OHLCV ڈیٹا حاصل: {len(df)} قطاریں")
                signal = await predictor.predict_signal(symbol, df, timeframe)
                signals[timeframe] = signal
                logger.info(f"[{symbol}] {timeframe} کے لیے سگنل: {signal}")
            except Exception as e:
                logger.error(f"[{symbol}] {timeframe} تجزیہ میں خرابی: {str(e)}")
                signals[timeframe] = None
                continue

        # درست سگنلز فلٹر کریں
        valid_signals = {t: s for t, s in signals.items() if s is not None}
        if len(valid_signals) < 2:
            logger.info(f"[{symbol}] ناکافی درست سگنلز: {len(valid_signals)}/{len(timeframes)}")
            return None

        # 2/4 ٹائم فریم ایگریمنٹ چیک
        directions = [s['direction'] for s in valid_signals.values()]
        direction_counts = pd.Series(directions).value_counts()
        most_common_direction = direction_counts.idxmax() if not direction_counts.empty else None
        agreement_count = direction_counts.get(most_common_direction, 0) if most_common_direction else 0

        if agreement_count < 2:  # کم از کم 2 ٹائم فریمز کا اتفاق
            logger.info(f"[{symbol}] ناکافی ٹائم فریم ایگریمنٹ: {agreement_count}/{len(timeframes)}")
            return None

        # اتفاق والے سگنلز منتخب کریں اور اوسط اعتماد کا حساب لگائیں
        agreed_signals = [s for s in valid_signals.values() if s['direction'] == most_common_direction]
        final_signal = agreed_signals[0].copy()
        final_signal['confidence'] = sum(s['confidence'] for s in agreed_signals) / len(agreed_signals)
        final_signal['timeframe'] = 'multi'
        final_signal['agreement'] = (agreement_count / len(timeframes)) * 100
        logger.info(f"[{symbol}] {agreement_count}/{len(timeframes)} ایگریمنٹ کے ساتھ سگنل منتخب، اعتماد: {final_signal['confidence']:.2f}%")

        # والیوم چیک
        df = await fetch_realtime_data(symbol, agreed_signals[0]['timeframe'], limit=50)
        if df is None:
            logger.warning(f"[{symbol}] والیوم چیک کے لیے ڈیٹا ناکام")
            return None

        latest = df.iloc[-1]
        if latest['quote_volume_24h'] < MIN_VOLUME:
            logger.info(f"[{symbol}] سگنل مسترد: کوٹ والیوم ${latest['quote_volume_24h']:,.2f} < ${MIN_VOLUME:,}")
            return None

        final_signal['timestamp'] = datetime.now(pytz.UTC).isoformat() + 'Z'
        return final_signal

    except Exception as e:
        logger.error(f"[{symbol}] ملٹی ٹائم فریم تجزیہ میں خرابی: {str(e)}")
        return None

# UTC ٹائم اسٹیمپ کو پاکستان ٹائم میں تبدیل کریں
def format_timestamp_to_pk(utc_timestamp_str):
    try:
        utc_time = datetime.fromisoformat(utc_timestamp_str.replace('Z', '+00:00'))
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
        pk_time = utc_time.astimezone(pytz.timezone("Asia/Karachi"))
        return pk_time.strftime("%d %B %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"ٹائم اسٹیمپ تبدیل کرنے میں خرابی: {str(e)}")
        return utc_timestamp_str

# TP امکانات کا حساب (غیر جانبدار)
def calculate_tp_probabilities(indicators):
    logger.info("انڈیکیٹرز کی بنیاد پر متحرک TP امکانات")
    base_prob = 50  # غیر جانبدار بیس
    if isinstance(indicators, str):
        indicators = indicators.split(", ")
    if "MACD" in indicators:  # Bullish/Bearish دونوں کے لیے یکساں
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

# 24 گھنٹے کا والیوم حاصل کریں
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

# سٹیبل کوائن کے لیے TP ایڈجسٹ کریں
def adjust_tp_for_stablecoin(symbol, tp1, tp2, tp3, entry):
    if "USDT" in symbol and symbol != "USDT/USD":
        max_tp_percent = 0.01
        tp1 = min(tp1, entry * (1 + max_tp_percent))
        tp2 = min(tp2, entry * (1 + max_tp_percent * 1.5))
        tp3 = min(tp3, entry * (1 + max_tp_percent * 2))
    return tp1, tp2, tp3

# ٹیلیگرام پر سگنل بھیجیں
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
            logger.info(f"ٹیلیگرام پر سگنل کامیابی سے بھیجا: {signal['symbol']} - {signal['direction']}")
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

# مین لوپ تمام USDT جوڑوں کے لیے
async def main_loop():
    exchange = ccxt.binance()
    timeframes = ["15m", "1h", "4h", "1d"]

    # تمام USDT جوڑوں کو لوڈ کریں
    try:
        markets = await exchange.load_markets()
        symbols = [s for s in markets.keys() if s.endswith("/USDT")]
        logger.info(f"{len(symbols)} USDT جوڑے ملے")
    except Exception as e:
        logger.error(f"مارکیٹس لوڈ کرنے میں خرابی: {str(e)}")
        return

    while True:
        for symbol in symbols:
            try:
                # والیوم چیک
                ticker = await exchange.fetch_ticker(symbol)
                quote_volume_24h = ticker.get('quoteVolume', 0)
                base_volume = ticker.get('baseVolume', 0)
                last_price = ticker.get('last', 0)
                if quote_volume_24h == 0 and base_volume > 0 and last_price > 0:
                    quote_volume_24h = base_volume * last_price
                if quote_volume_24h < MIN_VOLUME:
                    logger.info(f"[{symbol}] مسترد: کم والیوم (${quote_volume_24h:,.2f} < ${MIN_VOLUME:,})")
                    continue

                signal = await analyze_symbol_multi_timeframe(symbol, exchange, timeframes)
                if signal:
                    await send_signal(signal)
                    logger.info(f"{symbol} کے لیے سگنل پراسیس کیا: {signal}")
                else:
                    logger.info(f"{symbol} کے لیے کوئی سگنل نہیں بنا")
            except Exception as e:
                logger.error(f"{symbol} پراسیس کرنے میں خرابی: {str(e)}")
        logger.info("تجزیہ سائیکل مکمل۔ 180 سیکنڈ انتظار...")
        await asyncio.sleep(180)

# ٹیلیگرام بوٹ شروع کریں
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
            logger.info(f"ویب ہک سیٹ کیا: {WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"ویب ہک سیٹ کرنے میں خرابی: {str(e)}")
            raise

        try:
            await bot.send_message(chat_id=CHAT_ID, text="بوٹ کامیابی سے شروع!")
            logger.info("ٹیلیگرام پر ٹیسٹ پیغام بھیجا")
        except Exception as e:
            logger.error(f"ٹیسٹ پیغام بھیجنے میں ناکامی: {str(e)}")

        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Crypto Signal Bot چل رہا ہے!")))
        application.add_handler(CommandHandler("status", lambda u, c: u.message.reply_text("بوٹ چل رہا ہے۔")))
        await application.initialize()
        await application.start()
        logger.info("ٹیلیگرام ویب ہک بوٹ کامیابی سے شروع")
        return application
    except Exception as e:
        logger.error(f"ٹیلیگرام بوٹ شروع کرنے میں خرابی: {str(e)}")
        raise

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    loop.create_task(main_loop())
    loop.run_forever()
