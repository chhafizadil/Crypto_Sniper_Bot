import polars as pl
from utils.logger import logger
import ccxt.async_support as ccxt
import asyncio

async def track_trade(symbol, signal):
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        direction = signal["direction"]
        price = signal["price"]
        tp1 = signal["tp1"]
        tp2 = signal["tp2"]
        tp3 = signal["tp3"]
        sl = signal["sl"]

        status = "pending"
        for _ in range(720):  # Check for ~3 hours (720 * 15s)
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker["last"]

            if direction == "LONG":
                if current_price >= tp3:
                    status = "tp3"
                    break
                elif current_price >= tp2:
                    status = "tp2"
                elif current_price >= tp1:
                    status = "tp1"
                elif current_price <= sl:
                    status = "sl"
                    break
            else:  # SHORT
                if current_price <= tp3:
                    status = "tp3"
                    break
                elif current_price <= tp2:
                    status = "tp2"
                elif current_price <= tp1:
                    status = "tp1"
                elif current_price >= sl:
                    status = "sl"
                    break

            await asyncio.sleep(15)  # Check every 15 seconds

        log(f"[{symbol}] Trade status: {status}")
        update_signal_log(symbol, signal, status)
        await exchange.close()
        return status
    except Exception as e:
        log(f"[{symbol}] Error tracking trade: {e}", level='ERROR')
        await exchange.close()
        return "error"

def update_signal_log(symbol, signal, status):
    try:
        csv_path = "logs/signals_log.csv"
        df = pl.read_csv(csv_path)
        df = df.with_columns(pl.col("status").cast(pl.Utf8))
        df = df.with_columns(
            pl.when((pl.col("symbol") == symbol) & (pl.col("timestamp") == signal["timestamp"]))
            .then(status)
            .otherwise(pl.col("status"))
            .alias("status")
        )
        df.write_csv(csv_path)
        log(f"[{symbol}] Signal log updated with status: {status}")
    except Exception as e:
        log(f"[{symbol}] Error updating signal log: {e}", level='ERROR')
