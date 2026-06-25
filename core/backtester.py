import numpy as np
import pandas as pd
import json
from datetime import datetime
from .strategy import Strategy
from .risk_manager import RiskManager


class Backtester:
    def __init__(self, config):
        self.config = config
        self.strategy = Strategy(config)
        self.risk_manager = RiskManager(config)
        self.results = []

    def load_data_from_csv(self, filepath):
        try:
            df = pd.read_csv(filepath)
            return df.to_dict('records')
        except Exception as e:
            print(f"Error loading CSV: {e}")
            return []

    def run_backtest(self, klines_htf, klines_ltf, initial_capital=100000000):
        capital = initial_capital
        positions = []
        trades = []
        equity_curve = [capital]
        peak_equity = capital
        max_drawdown = 0
        offset = max(self.strategy.ema_slow_period, 50)

        entry_signals = []
        for i in range(offset, len(klines_ltf)):
            current_ltf = klines_ltf[max(0, i-200):i+1]
            current_htf = klines_htf

            if len(current_ltf) < 20:
                entry_signals.append(None)
                continue

            signal, trend, divergence = self.strategy.get_entry_signal(current_htf, current_ltf)
            entry_signals.append(signal)

        for i in range(len(entry_signals)):
            if entry_signals[i] in ['BUY', 'SELL']:
                kline_idx = i + offset
                if kline_idx >= len(klines_ltf):
                    continue
                current_price = klines_ltf[kline_idx]['close']
                direction = entry_signals[i]

                lot = self.risk_manager.calculate_lot(capital)
                if lot <= 0:
                    continue

                sl = self.strategy.calculate_stop_loss(
                    klines_ltf[:kline_idx+1], current_price, direction
                )
                tp = self.strategy.calculate_take_profit(
                    current_price, sl, direction
                )

                position = {
                    'direction': direction,
                    'entry_price': current_price,
                    'quantity': lot,
                    'sl': sl,
                    'tp': tp,
                    'entry_index': kline_idx
                }
                positions.append(position)

                trades.append({
                    'entry_time': klines_ltf[kline_idx].get('open_time', kline_idx),
                    'entry_price': current_price,
                    'direction': direction,
                    'quantity': lot,
                    'sl': sl,
                    'tp': tp
                })

        for trade in trades:
            direction = trade['direction']
            entry_price = trade['entry_price']
            quantity = trade['quantity']
            sl = trade['sl']
            tp = trade['tp']
            entry_idx = trade.get('entry_index', 0)

            exit_price = None
            for i in range(entry_idx + 1, len(klines_ltf)):
                high = klines_ltf[i]['high']
                low = klines_ltf[i]['low']

                if direction == 'BUY':
                    if low <= sl:
                        exit_price = sl
                        break
                    elif high >= tp:
                        exit_price = tp
                        break
                else:
                    if high >= sl:
                        exit_price = sl
                        break
                    elif low <= tp:
                        exit_price = tp
                        break

            if exit_price is None:
                exit_price = klines_ltf[-1]['close']

            if direction == 'BUY':
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity

            capital += pnl
            trade['exit_price'] = exit_price
            trade['pnl'] = pnl

            equity_curve.append(capital)
            peak_equity = max(peak_equity, capital)
            drawdown = ((peak_equity - capital) / peak_equity) * 100
            max_drawdown = max(max_drawdown, drawdown)

        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]

        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0

        avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
        avg_loss = abs(np.mean([t['pnl'] for t in losing_trades])) if losing_trades else 1
        profit_factor = (avg_win * len(winning_trades)) / (avg_loss * len(losing_trades)) if losing_trades else float('inf')

        returns = np.diff(equity_curve) / equity_curve[:-1]
        sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if len(returns) > 1 and np.std(returns) > 0 else 0

        total_pnl = capital - initial_capital
        roi = (total_pnl / initial_capital) * 100

        self.results = {
            'initial_capital': initial_capital,
            'final_capital': capital,
            'total_pnl': total_pnl,
            'roi': roi,
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'trades': trades
        }

        return self.results

    def display_results(self):
        if not self.results:
            print("No backtest results available")
            return

        print("\n" + "="*50)
        print("        BACKTEST RESULTS - KAMSIADI.Inc")
        print("="*50)

        print(f"\nInitial Capital : Rp {self.results['initial_capital']:,.2f}")
        print(f"Final Capital   : Rp {self.results['final_capital']:,.2f}")
        print(f"Total PnL       : Rp {self.results['total_pnl']:,.2f}")
        print(f"ROI             : {self.results['roi']:.2f}%")

        print(f"\nTotal Trades    : {self.results['total_trades']}")
        print(f"Winning Trades  : {self.results['winning_trades']}")
        print(f"Losing Trades   : {self.results['losing_trades']}")
        print(f"Win Rate        : {self.results['win_rate']:.2f}%")

        print(f"\nMax Drawdown    : {self.results['max_drawdown']:.2f}%")
        print(f"Sharpe Ratio    : {self.results['sharpe_ratio']:.2f}")
        print(f"Profit Factor   : {self.results['profit_factor']:.2f}")

        print(f"\nAverage Win     : Rp {self.results['avg_win']:,.2f}")
        print(f"Average Loss    : Rp {self.results['avg_loss']:,.2f}")

        print("\n" + "="*50)
        print("        TRADE HISTORY")
        print("="*50)

        for i, trade in enumerate(self.results.get('trades', [])[:20], 1):
            print(f"\nTrade #{i}:")
            print(f"  Direction: {trade['direction']}")
            print(f"  Entry: Rp {trade['entry_price']:,.2f}")
            print(f"  Exit: Rp {trade.get('exit_price', 'N/A'):,.2f}")
            print(f"  PnL: Rp {trade.get('pnl', 0):,.2f}")
