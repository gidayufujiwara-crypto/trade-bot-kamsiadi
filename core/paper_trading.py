import os
import sys
import sqlite3
from datetime import datetime


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PaperTradingEngine:
    def __init__(self, initial_balance=100000000):
        app_dir = get_app_dir()
        self.db_path = os.path.join(app_dir, 'paper_trades.db')
        self.initial_balance = initial_balance
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                total_idr REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'open',
                realized_pnl REAL DEFAULT 0,
                close_price REAL,
                close_timestamp DATETIME,
                entry_timestamp DATETIME,
                exit_reason TEXT,
                sl_price REAL DEFAULT 0,
                tp_price REAL DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                initial_balance REAL DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('SELECT id FROM paper_account WHERE id = 1')
        if not cursor.fetchone():
            cursor.execute('INSERT INTO paper_account (id, balance, initial_balance) VALUES (1, ?, ?)',
                          (self.initial_balance, self.initial_balance))
        conn.commit()
        conn.close()

    def get_balance(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM paper_account WHERE id = 1')
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else self.initial_balance

    def set_balance(self, amount):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE paper_account SET balance = ?, initial_balance = ?, last_updated = ? WHERE id = 1',
                      (amount, amount, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def get_equity(self, open_positions, current_prices):
        balance = self.get_balance()
        floating = 0
        for pos in open_positions:
            symbol = pos['symbol']
            side = pos['side']
            entry = pos['entry_price']
            qty = pos['quantity']
            curr = current_prices.get(symbol, entry)
            if side == 'BUY':
                floating += (curr - entry) * qty
            else:
                floating += (entry - curr) * qty
        return balance + floating

    def execute_order(self, symbol, side, quantity, price):
        balance = self.get_balance()
        total_idr = quantity * price

        if side == 'BUY':
            if balance < total_idr:
                return None, "Insufficient balance"
            new_balance = balance - total_idr
        else:
            open_pos = self._get_open_position(symbol)
            if not open_pos or open_pos[3] < quantity:
                return None, "No open position or insufficient quantity"
            new_balance = balance + total_idr

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO paper_trades (symbol, side, quantity, price, total_idr, status, entry_timestamp)
            VALUES (?, ?, ?, ?, ?, 'open', ?)
        ''', (symbol, side, quantity, price, total_idr, datetime.now().isoformat()))
        trade_id = cursor.lastrowid
        cursor.execute('UPDATE paper_account SET balance = ?, last_updated = ? WHERE id = 1',
                      (new_balance, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return trade_id, "OK"

    def close_position(self, trade_id, exit_price, reason="manual"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM paper_trades WHERE id = ?', (trade_id,))
        trade = cursor.fetchone()
        if not trade:
            conn.close()
            return 0

        symbol, side, quantity, entry_price = trade[1], trade[2], trade[3], trade[4]
        if side == 'BUY':
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        balance = self.get_balance()
        new_balance = balance + pnl + (quantity * entry_price if side == 'SELL' else 0)

        cursor.execute('''
            UPDATE paper_trades SET status = 'closed', realized_pnl = ?,
            close_price = ?, close_timestamp = ?, exit_reason = ?
            WHERE id = ?
        ''', (pnl, exit_price, datetime.now().isoformat(), reason, trade_id))
        cursor.execute('UPDATE paper_account SET balance = ?, last_updated = ? WHERE id = 1',
                      (new_balance, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return pnl

    def close_all_positions(self, current_prices):
        open_trades = self.get_open_trades()
        total_pnl = 0
        for trade in open_trades:
            trade_id = trade[0]
            symbol = trade[1]
            price = current_prices.get(symbol, trade[4])
            pnl = self.close_position(trade_id, price, "force_close")
            total_pnl += pnl
        return total_pnl

    def get_open_trades(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM paper_trades WHERE status = "open"')
        trades = cursor.fetchall()
        conn.close()
        return trades

    def get_closed_trades(self, limit=50):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM paper_trades WHERE status = "closed" ORDER BY id DESC LIMIT ?', (limit,))
        trades = cursor.fetchall()
        conn.close()
        return trades

    def get_stats(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM paper_trades WHERE status = "closed"')
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM paper_trades WHERE status = "closed" AND realized_pnl > 0')
        wins = cursor.fetchone()[0]
        cursor.execute('SELECT SUM(realized_pnl) FROM paper_trades WHERE status = "closed"')
        total_pnl = cursor.fetchone()[0] or 0
        cursor.execute('SELECT AVG(realized_pnl) FROM paper_trades WHERE status = "closed" AND realized_pnl > 0')
        avg_win = cursor.fetchone()[0] or 0
        cursor.execute('SELECT AVG(realized_pnl) FROM paper_trades WHERE status = "closed" AND realized_pnl <= 0')
        avg_loss = cursor.fetchone()[0] or 0
        conn.close()
        win_rate = (wins / total * 100) if total > 0 else 0
        return {
            'total_trades': total,
            'winning_trades': wins,
            'losing_trades': total - wins,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'balance': self.get_balance()
        }

    def reset_account(self, new_balance=None):
        balance = new_balance if new_balance else self.initial_balance
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM paper_trades')
        cursor.execute('UPDATE paper_account SET balance = ?, initial_balance = ?, last_updated = ? WHERE id = 1',
                      (balance, balance, datetime.now().isoformat()))
        conn.commit()
        conn.close()
