import requests


class TelegramBot:
    def __init__(self, config):
        self.enabled = config['telegram'].get('enabled', False)
        self.token = config['telegram'].get('token', '')
        self.chat_id = config['telegram'].get('chat_id', '')
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.command_handlers = {}
        self._offset = 0

    def send_message(self, message, parse_mode='Markdown'):
        if not self.enabled or not self.token or not self.chat_id:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def send_bot_start(self):
        return self.send_message("*KAMSIADI.Inc Bot*\n\nBot Started and Ready to Trade")

    def send_bot_stop(self):
        return self.send_message("*KAMSIADI.Inc Bot*\n\nBot Stopped")

    def send_entry_signal(self, direction, symbol, price, lot):
        emoji = "BUY" if direction == "BUY" else "SELL"
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Entry Signal*\n"
            f"Direction: {emoji}\n"
            f"Symbol: {symbol}\n"
            f"Price: Rp {price:,.2f}\n"
            f"Lot: {lot:.6f}"
        )
        return self.send_message(message)

    def send_exit_signal(self, symbol, entry_price, exit_price, pnl, direction):
        status = "PROFIT" if pnl > 0 else "LOSS"
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Position Closed*\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Entry: Rp {entry_price:,.2f}\n"
            f"Exit: Rp {exit_price:,.2f}\n"
            f"Status: {status}\nPnL: Rp {pnl:,.2f}"
        )
        return self.send_message(message)

    def send_drawdown_warning(self, current_loss, max_loss):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*DAILY DRAWDOWN WARNING*\n"
            f"Current Loss: Rp {current_loss:,.2f}\n"
            f"Max Loss: Rp {max_loss:,.2f}\n"
            f"Usage: {(current_loss/max_loss)*100:.1f}%"
        )
        return self.send_message(message)

    def send_drawdown_triggered(self, total_loss):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*DAILY DRAWDOWN TERCAPAI!*\n"
            f"Total Loss: Rp {total_loss:,.2f}\n"
            f"Bot di-stop otomatis."
        )
        return self.send_message(message)

    def send_error(self, error_message):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Error*\n"
            f"{error_message}"
        )
        return self.send_message(message)

    def send_adaptive_switch(self, old_tier, new_tier, balance):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Adaptive Strategy Switched*\n"
            f"{old_tier} -> {new_tier}\n"
            f"Saldo: Rp {balance:,.0f}"
        )
        return self.send_message(message)

    def send_session_status(self, status, time_info):
        if status == "PAUSED":
            msg = f"Trading Session Paused. Bot akan lanjut {time_info}."
        else:
            msg = f"Trading Session Resumed. Active until {time_info}."
        return self.send_message(f"*KAMSIADI.Inc Bot*\n\n{msg}")

    def send_max_hold_warning(self, symbol, remaining_minutes):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Max Hold Warning*\n"
            f"Position {symbol} will expire in {remaining_minutes} minutes."
        )
        return self.send_message(message)

    def send_max_hold_closed(self, symbol, holding_time, pnl):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Position Closed (Max Hold)*\n"
            f"Symbol: {symbol}\n"
            f"Holding Time: {holding_time}\n"
            f"PnL: Rp {pnl:,.2f}"
        )
        return self.send_message(message)

    def send_profit_report(self, realized, floating, total):
        message = (
            f"*KAMSIADI.Inc Bot*\n\n"
            f"*Daily Profit Report*\n"
            f"Realized: Rp {realized:,.2f}\n"
            f"Floating: Rp {floating:,.2f}\n"
            f"Total: Rp {total:,.2f}"
        )
        return self.send_message(message)

    def send_positions_report(self, positions):
        if not positions:
            return self.send_message("*KAMSIADI.Inc Bot*\n\nNo open positions.")
        lines = ["*KAMSIADI.Inc Bot*\n\n*Open Positions:*"]
        for i, p in enumerate(positions, 1):
            pnl_pct = p.get('pnl_pct', 0)
            sign = "+" if pnl_pct >= 0 else ""
            time_left = p.get('time_left', 'N/A')
            lines.append(f"{i}. {p['symbol']} | Entry: Rp {p['entry']:,.0f} | PnL: {sign}{pnl_pct:.1f}% | Time Left: {time_left}")
        return self.send_message("\n".join(lines))

    def send_settings_report(self, config):
        msg = (
            f"*KAMSIADI.Inc Bot*\n\n*Current Settings:*\n"
            f"Mode: {config.get('trading_mode', 'N/A')}\n"
            f"Exchange: {config.get('exchange', {}).get('name', 'N/A')}\n"
            f"Entry TF: {config.get('timeframe', {}).get('entry', 'N/A')}\n"
            f"Trend TF: {config.get('timeframe', {}).get('trend', 'N/A')}\n"
            f"Max Positions: {config.get('risk_management', {}).get('max_positions', 'N/A')}\n"
            f"R:R Ratio: {config.get('risk_management', {}).get('min_rr_ratio', 'N/A')}\n"
            f"Max Hold: {config.get('max_holding_time', {}).get('max_hours', 'N/A')}h\n"
            f"Session: {config.get('trading_session', {}).get('start_time', 'N/A')}-{config.get('trading_session', {}).get('end_time', 'N/A')}\n"
            f"Drawdown: {config.get('daily_drawdown', {}).get('max_loss_idr', 'N/A')} IDR"
        )
        return self.send_message(msg)

    def send_stop_confirm_request(self):
        return self.send_message(
            "*KAMSIADI.Inc Bot*\n\n"
            "Are you sure you want to stop the bot?\n"
            "Reply with /confirm_stop to confirm."
        )

    def register_commands(self):
        self.command_handlers = {
            '/profit': self._handle_profit,
            '/positions': self._handle_positions,
            '/stop': self._handle_stop,
            '/confirm_stop': self._handle_confirm_stop,
            '/resume': self._handle_resume,
            '/settings': self._handle_settings,
        }

    def set_handlers(self, profit_fn=None, positions_fn=None, stop_fn=None, resume_fn=None, get_config_fn=None):
        self._profit_fn = profit_fn
        self._positions_fn = positions_fn
        self._stop_fn = stop_fn
        self._resume_fn = resume_fn
        self._get_config_fn = get_config_fn

    def _handle_profit(self):
        if hasattr(self, '_profit_fn') and self._profit_fn:
            data = self._profit_fn()
            self.send_profit_report(data.get('realized', 0), data.get('floating', 0), data.get('total', 0))

    def _handle_positions(self):
        if hasattr(self, '_positions_fn') and self._positions_fn:
            positions = self._positions_fn()
            self.send_positions_report(positions)

    def _handle_stop(self):
        self.send_stop_confirm_request()

    def _handle_confirm_stop(self):
        if hasattr(self, '_stop_fn') and self._stop_fn:
            self._stop_fn()

    def _handle_resume(self):
        if hasattr(self, '_resume_fn') and self._resume_fn:
            self._resume_fn()
            self.send_message("*KAMSIADI.Inc Bot*\n\nBot Resumed.")

    def _handle_settings(self):
        if hasattr(self, '_get_config_fn') and self._get_config_fn:
            config = self._get_config_fn()
            self.send_settings_report(config)

    def get_updates(self):
        if not self.enabled or not self.token:
            return []
        try:
            url = f"{self.base_url}/getUpdates"
            response = requests.get(url, params={'offset': self._offset, 'timeout': 5}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = data.get('result', [])
                if results:
                    self._offset = results[-1]['update_id'] + 1
                return results
        except Exception:
            pass
        return []

    def poll_commands(self):
        if not self.enabled or not self.command_handlers:
            return
        updates = self.get_updates()
        for update in updates:
            if 'message' in update and 'text' in update['message']:
                text = update['message']['text'].strip().lower()
                if text in self.command_handlers:
                    self.command_handlers[text]()
