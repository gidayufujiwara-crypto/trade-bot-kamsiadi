import numpy as np
import pandas as pd
from datetime import datetime


class Strategy:
    def __init__(self, config):
        self.config = config
        self.ema_fast_period = config['strategy']['ema_fast']
        self.ema_slow_period = config['strategy']['ema_slow']
        self.rsi_period = config['strategy']['rsi_period']
        self.divergence_indicator = config['strategy']['divergence_indicator']
        self.macd_fast = config['strategy']['macd_fast']
        self.macd_slow = config['strategy']['macd_slow']
        self.macd_signal = config['strategy']['macd_signal']
        self.doji_threshold = config['strategy']['doji_threshold']

    def calculate_ema(self, data, period):
        if len(data) < period:
            return np.zeros(len(data))
        ema = pd.Series(data).ewm(span=period, adjust=False).mean().values
        return ema

    def calculate_rsi(self, data, period):
        if len(data) < period + 1:
            return np.zeros(len(data))
        delta = np.diff(data, prepend=data[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        avg_gain = pd.Series(gain).rolling(window=period).mean().values
        avg_loss = pd.Series(loss).rolling(window=period).mean().values

        rs = np.where(avg_loss != 0, avg_gain / avg_loss, 0)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, data):
        ema_fast = self.calculate_ema(data, self.macd_fast)
        ema_slow = self.calculate_ema(data, self.macd_slow)
        macd_line = ema_fast - ema_slow
        signal_line = self.calculate_ema(macd_line, self.macd_signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def calculate_atr(self, klines, period=14):
        if len(klines) < period:
            return np.zeros(len(klines))

        highs = np.array([k['high'] for k in klines])
        lows = np.array([k['low'] for k in klines])
        closes = np.array([k['close'] for k in klines])

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        tr = np.insert(tr, 0, highs[0] - lows[0])

        atr = pd.Series(tr).rolling(window=period).mean().values
        return atr

    def determine_trend(self, klines):
        if len(klines) < self.ema_slow_period:
            return "NEUTRAL"

        closes = np.array([k['close'] for k in klines])
        ema_fast = self.calculate_ema(closes, self.ema_fast_period)
        ema_slow = self.calculate_ema(closes, self.ema_slow_period)

        current_price = closes[-1]
        current_ema_fast = ema_fast[-1]
        current_ema_slow = ema_slow[-1]
        prev_ema_fast = ema_fast[-2] if len(ema_fast) > 1 else current_ema_fast

        ema_fast_slope = current_ema_fast - prev_ema_fast

        if current_price > current_ema_fast and current_ema_fast > current_ema_slow and ema_fast_slope > 0:
            return "UPTREND"
        elif current_price < current_ema_fast and current_ema_fast < current_ema_slow and ema_fast_slope < 0:
            return "DOWNTREND"
        else:
            return "NEUTRAL"

    def find_divergence(self, klines, indicator_type='RSI'):
        if len(klines) < 50:
            return None

        closes = np.array([k['close'] for k in klines])
        highs = np.array([k['high'] for k in klines])
        lows = np.array([k['low'] for k in klines])

        if indicator_type == 'RSI':
            indicator_values = self.calculate_rsi(closes, self.rsi_period)
        elif indicator_type == 'MACD':
            _, _, indicator_values = self.calculate_macd(closes)
        else:
            indicator_values = self.calculate_rsi(closes, self.rsi_period)

        lookback = min(30, len(klines) - 1)

        recent_closes = closes[-lookback:]
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        recent_indicator = indicator_values[-lookback:]

        min_price_idx = np.argmin(recent_closes)
        prev_closes = recent_closes[:min_price_idx]
        prev_indicator = recent_indicator[:min_price_idx]

        if len(prev_closes) < 10:
            return None

        prev_min_idx = np.argmin(prev_closes)

        if recent_closes[min_price_idx] < prev_closes[prev_min_idx]:
            if recent_indicator[min_price_idx] > prev_indicator[prev_min_idx]:
                return "BULLISH_DIVERGENCE"

        max_price_idx = np.argmax(recent_closes)
        prev_highs_closes = recent_closes[:max_price_idx]
        prev_highs_indicator = recent_indicator[:max_price_idx]

        if len(prev_highs_closes) < 10:
            return None

        prev_max_idx = np.argmax(prev_highs_closes)

        if recent_closes[max_price_idx] > prev_highs_closes[prev_max_idx]:
            if recent_indicator[max_price_idx] < prev_highs_indicator[prev_max_idx]:
                return "BEARISH_DIVERGENCE"

        return None

    def is_doji_or_hammer(self, klines, threshold=None):
        if threshold is None:
            threshold = self.doji_threshold

        last_candle = klines[-1]
        body = abs(last_candle['close'] - last_candle['open'])
        range_size = last_candle['high'] - last_candle['low']

        if range_size == 0:
            return True

        body_ratio = body / range_size
        return body_ratio < threshold

    def get_entry_signal(self, klines_htf, klines_ltf):
        trend = self.determine_trend(klines_htf)
        divergence = self.find_divergence(klines_ltf, self.divergence_indicator)

        if divergence and self.is_doji_or_hammer(klines_ltf):
            return None, trend, divergence

        if trend == "UPTREND" and divergence == "BULLISH_DIVERGENCE":
            return "BUY", trend, divergence
        elif trend == "DOWNTREND" and divergence == "BEARISH_DIVERGENCE":
            return "SELL", trend, divergence

        return None, trend, divergence

    def calculate_stop_loss(self, klines, entry_price, direction, atr_multiplier=1.5, atr_period=14):
        atr = self.calculate_atr(klines, atr_period)
        current_atr = atr[-1] if len(atr) > 0 else 0

        if current_atr == 0:
            return entry_price * (0.98 if direction == "BUY" else 1.02)

        sl_distance = current_atr * atr_multiplier

        if direction == "BUY":
            return entry_price - sl_distance
        else:
            return entry_price + sl_distance

    def calculate_take_profit(self, entry_price, stop_loss, direction, rr_ratio=2.0):
        risk = abs(entry_price - stop_loss)
        reward = risk * rr_ratio

        if direction == "BUY":
            return entry_price + reward
        else:
            return entry_price - reward
