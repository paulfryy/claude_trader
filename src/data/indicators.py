"""
Technical indicator calculations.
Wraps the `ta` library for common indicators used in swing trading analysis.
"""

import pandas as pd
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a standard set of technical indicators to an OHLCV DataFrame.
    Expects columns: open, high, low, close, volume.
    Returns the DataFrame with indicator columns added.
    """
    df = df.copy()

    # Trend
    df["sma_20"] = SMAIndicator(close=df["close"], window=20).sma_indicator()
    df["sma_50"] = SMAIndicator(close=df["close"], window=50).sma_indicator()
    df["ema_12"] = EMAIndicator(close=df["close"], window=12).ema_indicator()
    df["ema_26"] = EMAIndicator(close=df["close"], window=26).ema_indicator()

    # MACD
    macd = MACD(close=df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()

    # Momentum
    df["rsi_14"] = RSIIndicator(close=df["close"], window=14).rsi()
    stoch_rsi = StochRSIIndicator(close=df["close"], window=14)
    df["stoch_rsi_k"] = stoch_rsi.stochrsi_k()
    df["stoch_rsi_d"] = stoch_rsi.stochrsi_d()

    # Volatility
    bb = BollingerBands(close=df["close"], window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["atr_14"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    # Volume
    df["obv"] = OnBalanceVolumeIndicator(
        close=df["close"], volume=df["volume"]
    ).on_balance_volume()
    if len(df) >= 14:
        df["vwap"] = VolumeWeightedAveragePrice(
            high=df["high"], low=df["low"], close=df["close"], volume=df["volume"]
        ).volume_weighted_average_price()

    return df


def summarize_indicators(df: pd.DataFrame) -> dict:
    """
    Produce a human-readable summary of the latest indicator values.
    Useful for feeding into Claude's analysis prompt.
    """
    if df.empty:
        return {}

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    summary = {
        "price": latest.get("close"),
        "sma_20": latest.get("sma_20"),
        "sma_50": latest.get("sma_50"),
        "price_vs_sma20": "above" if latest["close"] > latest.get("sma_20", 0) else "below",
        "price_vs_sma50": "above" if latest["close"] > latest.get("sma_50", 0) else "below",
        "rsi_14": latest.get("rsi_14"),
        "rsi_signal": (
            "oversold" if latest.get("rsi_14", 50) < 30
            else "overbought" if latest.get("rsi_14", 50) > 70
            else "neutral"
        ),
        "macd": latest.get("macd"),
        "macd_signal": latest.get("macd_signal"),
        "macd_crossover": (
            "bullish" if latest.get("macd", 0) > latest.get("macd_signal", 0)
            and prev.get("macd", 0) <= prev.get("macd_signal", 0)
            else "bearish" if latest.get("macd", 0) < latest.get("macd_signal", 0)
            and prev.get("macd", 0) >= prev.get("macd_signal", 0)
            else "none"
        ),
        "bb_position": (
            "above_upper" if latest["close"] > latest.get("bb_upper", float("inf"))
            else "below_lower" if latest["close"] < latest.get("bb_lower", 0)
            else "within"
        ),
        "atr_14": latest.get("atr_14"),
    }
    return summary
