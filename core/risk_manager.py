import os
import sys
import time
import json
import sqlite3
import threading
from datetime import datetime, date


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RiskManager:
    def __init__(self, config):
        self.config = config
        self.daily_drawdown = config['daily_drawdown']
        self.auto_lot_balance = config['risk_management']['auto_lot_balance']
        self.risk_multiplier = config['risk_management'].get('risk_multiplier', 1)
        self.max_positions = config['risk_management'].get('max_positions', 3)
        self.pyramiding_trigger = config['risk_management'].get('pyramiding_trigger_percent', 1.0)

        app_dir = get_app_dir()
        self.db_path = os.path.join(app_dir, 'trades.db')
        self._lock = threading.Lock()
        self.init_database()

        self.daily_loss = 0
        self.floating_loss = 0
        self.total_positions = self._count_open_trades()
        self.bot_status = "READY"
        self.last_reset_date = date.today()

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                total_idr REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'OPEN',
                realized_pnl REAL DEFAULT 0,
                sl_price REAL DEFAULT 0,
                tp_price REAL DEFAULT 0,
                exit_reason TEXT DEFAULT ''
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                realized_loss REAL DEFAULT 0,
                floating_loss REAL DEFAULT 0,
                total_loss REAL DEFAULT 0,
                trades_count INTEGER DEFAULT 0
            )
        ''')
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN sl_price REAL DEFAULT 0')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN tp_price REAL DEFAULT 0')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE trades ADD COLUMN exit_reason TEXT DEFAULT ""')
        except Exception:
            pass
        conn.commit()
        conn.close()

    def _count_open_trades(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM trades WHERE status = "OPEN"')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def calculate_lot(self, idr_balance):
        base_lot = (idr_balance / self.auto_lot_balance) * 0.001
        return base_lot * self.risk_multiplier

    def get_daily_loss(self):
        today = date.today().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT realized_loss FROM daily_pnl WHERE date = ?', (today,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    def update_daily_pnl(self, loss):
        today = date.today().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT id FROM daily_pnl WHERE date = ?', (today,))
        exists = cursor.fetchone()

        if exists:
            cursor.execute('''
                UPDATE daily_pnl 
                SET realized_loss = realized_loss + ?,
                    trades_count = trades_count + 1
                WHERE date = ?
            ''', (loss, today))
        else:
            cursor.execute('''
                INSERT INTO daily_pnl (date, realized_loss, trades_count)
                VALUES (?, ?, 1)
            ''', (today, loss))

        conn.commit()
        conn.close()

    def check_daily_drawdown(self, current_equity, initial_equity, timezone=None):
        if not self.daily_drawdown['enabled']:
            return False

        self._check_daily_reset(timezone)

        realized_loss = self.get_daily_loss()

        equity_loss = initial_equity - current_equity
        equity_loss_percent = (equity_loss / initial_equity) * 100 if initial_equity > 0 else 0

        max_loss_idr = self.daily_drawdown.get('max_loss_idr', 500000)
        max_loss_percent = self.daily_drawdown.get('max_loss_percent', 5)

        total_loss = realized_loss + self.floating_loss

        if total_loss >= max_loss_idr or equity_loss_percent >= max_loss_percent:
            return True

        return False

    def _check_daily_reset(self, timezone=None):
        try:
            from datetime import timezone as tz
            if timezone:
                now = datetime.now(timezone)
            else:
                now = datetime.now()
        except Exception:
            now = datetime.now()

        today = now.date()
        reset_time = self.daily_drawdown.get('reset_time', '00:00')
        parts = reset_time.split(':')
        reset_hour = int(parts[0])
        reset_min = int(parts[1])

        if now.hour == reset_hour and now.minute == reset_min and self.last_reset_date != today:
            self.daily_loss = 0
            self.floating_loss = 0
            self.bot_status = "READY"
            self.last_reset_date = today
            self._reset_db_daily(today.isoformat())
            return True

        return False

    def _reset_db_daily(self, date_str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM daily_pnl WHERE date = ?', (date_str,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute('UPDATE daily_pnl SET realized_loss = 0, floating_loss = 0, total_loss = 0, trades_count = 0 WHERE date = ?', (date_str,))
            else:
                cursor.execute('INSERT INTO daily_pnl (date, realized_loss, floating_loss, total_loss, trades_count) VALUES (?, 0, 0, 0, 0)', (date_str,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def can_open_position(self):
        if self.bot_status == "PAUSED":
            return False
        if self.total_positions >= self.max_positions:
            return False
        return True

    def has_open_position_for_pair(self, symbol):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM trades WHERE symbol = ? AND status = "OPEN"', (symbol,))
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception:
            return False

    def can_add_position(self, current_entry_price, new_entry_price, direction):
        if self.total_positions >= self.max_positions:
            return False

        if direction == "BUY":
            price_change = ((new_entry_price - current_entry_price) / current_entry_price) * 100
        else:
            price_change = ((current_entry_price - new_entry_price) / current_entry_price) * 100

        return price_change >= self.pyramiding_trigger

    def record_trade(self, symbol, side, quantity, price, status='OPEN', sl_price=0, tp_price=0):
        total_idr = quantity * price

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trades (symbol, side, quantity, price, total_idr, status, sl_price, tp_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, side, quantity, price, total_idr, status, sl_price, tp_price))
        conn.commit()
        trade_id = cursor.lastrowid
        conn.close()

        self.total_positions += 1
        return trade_id

    def close_trade(self, trade_id, exit_price, reason=""):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM trades WHERE id = ? AND status = "OPEN"', (trade_id,))
            trade = cursor.fetchone()

            if not trade:
                conn.close()
                return None

            cursor.execute('UPDATE trades SET status = "CLOSING" WHERE id = ? AND status = "OPEN"', (trade_id,))
            if cursor.rowcount == 0:
                conn.close()
                return None

            conn.commit()

            symbol, side, quantity, entry_price = trade[1], trade[2], trade[3], trade[4]

            if side == 'BUY':
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity

            cursor.execute('''
                UPDATE trades 
                SET status = 'CLOSED', realized_pnl = ?, exit_reason = ?
                WHERE id = ?
            ''', (pnl, reason, trade_id))

            conn.commit()
            self.total_positions = max(0, self.total_positions - 1)

            if pnl < 0:
                self.update_daily_pnl(abs(pnl))

            conn.close()
            return pnl

    def get_open_trades(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM trades WHERE status = "OPEN"')
        trades = cursor.fetchall()
        conn.close()
        return trades

    def is_trade_closing_or_closed(self, trade_id):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT status FROM trades WHERE id = ?', (trade_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0] in ('CLOSING', 'CLOSED'):
                return True
            return False
        except Exception:
            return True

    def update_floating_loss(self, open_trades, current_prices):
        total_floating = 0
        for trade in open_trades:
            trade_id, symbol, side, quantity, entry_price = trade[0], trade[1], trade[2], trade[3], trade[4]
            current_price = current_prices.get(symbol, entry_price)

            if side == 'BUY':
                floating = (current_price - entry_price) * quantity
            else:
                floating = (entry_price - current_price) * quantity

            total_floating += floating

        self.floating_loss = abs(total_floating) if total_floating < 0 else 0
        return total_floating

    def get_daily_stats(self):
        today = date.today().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM daily_pnl WHERE date = ?', (today,))
        row = cursor.fetchone()

        cursor.execute('SELECT COUNT(*) FROM trades WHERE status = "OPEN"')
        open_positions = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM trades WHERE date(timestamp) = ?', (today,))
        today_trades = cursor.fetchone()[0]

        conn.close()

        if row:
            realized = float(row[2]) if row[2] else 0
            return {
                'realized_loss': realized,
                'floating_loss': self.floating_loss,
                'total_loss': realized + self.floating_loss,
                'trades_count': int(row[5]) if row[5] else 0,
                'open_positions': open_positions,
                'today_trades': today_trades
            }
        return {
            'realized_loss': 0,
            'floating_loss': 0,
            'total_loss': 0,
            'trades_count': 0,
            'open_positions': open_positions,
            'today_trades': today_trades
        }
