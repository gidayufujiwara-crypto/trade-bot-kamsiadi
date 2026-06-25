import os
import sys
import shutil
import logging
from datetime import datetime


def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Logger:
    def __init__(self, log_dir='logs'):
        app_dir = get_app_dir()
        self.log_dir = os.path.join(app_dir, log_dir)
        self.archive_dir = os.path.join(self.log_dir, 'archive')
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        self.logger = logging.getLogger('KAMSIADI_Bot')
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(self.log_dir, f'bot_{today}.log')

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '[KAMSIADI.Inc][%(levelname)s] %(asctime)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.gui_callback = None
        self.gui_error_callback = None

    def set_gui_callback(self, callback):
        self.gui_callback = callback

    def set_gui_error_callback(self, callback):
        self.gui_error_callback = callback

    def _log(self, level, message):
        formatted = f"[KAMSIADI.Inc][{level}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}"
        if self.gui_callback:
            self.gui_callback(formatted)
        return formatted

    def info(self, message):
        self._log('INFO', message)
        self.logger.info(message)

    def warning(self, message):
        self._log('WARNING', message)
        self.logger.warning(message)

    def error(self, message, show_in_gui=False):
        self._log('ERROR', message)
        self.logger.error(message)
        if show_in_gui and self.gui_error_callback:
            self.gui_error_callback(message)

    def debug(self, message):
        self._log('DEBUG', message)
        self.logger.debug(message)

    def critical(self, message):
        self._log('CRITICAL', message)
        self.logger.critical(message)

    def trade(self, action, symbol, quantity, price):
        message = f"TRADE: {action} {quantity} {symbol} @ Rp {price:,.2f}"
        self._log('TRADE', message)
        self.logger.info(message)

    def drawdown_warning(self, current_loss, max_loss):
        message = f"DRAWDOWN WARNING: Rp {current_loss:,.2f} / Rp {max_loss:,.2f}"
        self._log('WARNING', message)
        self.logger.warning(message)

    def drawdown_triggered(self, total_loss):
        message = f"DRAWDOWN LIMIT REACHED! Total Loss: Rp {total_loss:,.2f}. Bot STOPPED."
        self._log('CRITICAL', message)
        self.logger.critical(message)

    def archive_old_logs(self, keep_days=7):
        try:
            today = datetime.now()
            for fname in os.listdir(self.log_dir):
                if not fname.startswith('bot_') or not fname.endswith('.log'):
                    continue
                fpath = os.path.join(self.log_dir, fname)
                date_str = fname.replace('bot_', '').replace('.log', '')
                try:
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    age = (today - file_date).days
                    if age > keep_days:
                        archive_name = fname.replace('.log', '_ARCHIVED.log')
                        dest = os.path.join(self.archive_dir, archive_name)
                        shutil.move(fpath, dest)
                except ValueError:
                    continue
        except Exception:
            pass

    def get_archive_dir(self):
        return self.archive_dir
