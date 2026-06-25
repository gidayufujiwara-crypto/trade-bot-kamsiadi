import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import json
import time
import sys
import os
import subprocess
from datetime import datetime
from core.exchange import Exchange
from core.strategy import Strategy
from core.risk_manager import RiskManager
from core.backtester import Backtester
from core.time_manager import TimeManager
from core.adaptive_strategy import AdaptiveStrategy
from core.webhook_server import WebhookServer
from core.paper_trading import PaperTradingEngine
from utils.logger import Logger
from utils.telegram_bot import TelegramBot


class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Private Trading Bot KAMSIADI.Inc")
        self.root.geometry("950x750")
        self.root.minsize(800, 600)

        self.config_created = False
        self.config = self.load_config()
        self.exchange = Exchange(self.config)
        self.strategy = Strategy(self.config)
        self.risk_manager = RiskManager(self.config)
        self.time_manager = TimeManager(self.config)
        self.adaptive = AdaptiveStrategy(self.config)
        self.logger = Logger()
        self.telegram = TelegramBot(self.config)
        self.webhook_server = WebhookServer(self.config, logger=self.logger)
        try:
            initial_balance = self.config.get('risk_management', {}).get('auto_lot_balance', 10000000) * 10
            self.paper_engine = PaperTradingEngine(initial_balance)
        except Exception as e:
            print(f"Paper engine init error: {e}")
            from core.paper_trading import PaperTradingEngine
            self.paper_engine = PaperTradingEngine(100000000)

        self.logger.set_gui_callback(self.append_log)
        self.logger.set_gui_error_callback(self.show_api_error)

        self.bot_running = False
        self.bot_thread = None
        self.stop_event = threading.Event()
        self.session_paused = False
        self.warned_holdings = set()

        self.balances = {}
        self.trading_pairs = []
        self.all_pairs = []
        self.current_mode = self.config.get('trading_mode', 'BUY & SELL')

        self.setup_gui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if self.config_created:
            self.root.after(500, self.show_first_run_message)

        self.telegram.register_commands()
        self.telegram.set_handlers(
            profit_fn=self._get_profit_data,
            positions_fn=self._get_positions_data,
            stop_fn=self._telegram_stop,
            resume_fn=self._telegram_resume,
            get_config_fn=lambda: self.config
        )

    def get_app_dir(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def get_bundle_dir(self):
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(__file__))

    def load_config(self):
        app_dir = self.get_app_dir()
        config_path = os.path.join(app_dir, 'config.json')
        try:
            bundle_dir = self.get_bundle_dir()
            bundled_config = os.path.join(bundle_dir, 'config.json')
            if not os.path.exists(config_path) and os.path.exists(bundled_config):
                import shutil
                shutil.copy2(bundled_config, config_path)
                self.config_created = True
        except Exception:
            pass
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self):
        app_dir = self.get_app_dir()
        config_path = os.path.join(app_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    def setup_gui(self):
        self.root.configure(bg='#1e1e1e')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#2d2d2d')
        style.configure('TNotebook.Tab', background='#3d3d3d', foreground='white', padding=[12, 4])
        style.map('TNotebook.Tab', background=[('selected', '#0066aa')])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.setup_dashboard_tab()
        self.setup_settings_tab()
        self.setup_charts_tab()
        self.setup_backtest_tab()
        self.setup_paper_tab()

    def setup_dashboard_tab(self):
        dashboard = tk.Frame(self.notebook, bg='#1e1e1e')
        self.notebook.add(dashboard, text="  Dashboard  ")

        title_frame = tk.Frame(dashboard, bg='#2d2d2d', height=50)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="PRIVATE TRADING BOT KAMSIADI.Inc  |  v1.0.0", font=('Consolas', 11, 'bold'), fg='#00ff00', bg='#2d2d2d').pack(side=tk.LEFT, padx=10, pady=8)

        self.status_label = tk.Label(title_frame, text="Disconnected", font=('Arial', 10, 'bold'), fg='#ff0000', bg='#2d2d2d')
        self.status_label.pack(side=tk.RIGHT, padx=20)

        self.api_error_label = tk.Label(dashboard, text="", font=('Arial', 9), fg='#ff0000', bg='#1e1e1e', wraplength=600)
        self.api_error_label.pack(fill=tk.X, padx=10)

        info_frame = tk.Frame(dashboard, bg='#3d3d3d', height=85)
        info_frame.pack(fill=tk.X, padx=5, pady=3)
        info_frame.pack_propagate(False)

        balance_frame = tk.Frame(info_frame, bg='#3d3d3d')
        balance_frame.pack(side=tk.LEFT, padx=10, fill=tk.Y)
        tk.Label(balance_frame, text="Saldo:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(anchor=tk.W)
        self.balance_idr_label = tk.Label(balance_frame, text="IDR: Rp 0", font=('Arial', 9), fg='#00ff00', bg='#3d3d3d')
        self.balance_idr_label.pack(anchor=tk.W)
        self.balance_coin_label = tk.Label(balance_frame, text="BTC: 0 | ETH: 0", font=('Arial', 9), fg='#00ff00', bg='#3d3d3d')
        self.balance_coin_label.pack(anchor=tk.W)

        mode_frame = tk.Frame(info_frame, bg='#3d3d3d')
        mode_frame.pack(side=tk.LEFT, padx=15, fill=tk.Y)
        tk.Label(mode_frame, text="Mode:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(anchor=tk.W)
        self.mode_label = tk.Label(mode_frame, text="BUY & SELL", font=('Arial', 9, 'bold'), fg='white', bg='#666666', padx=10, pady=2)
        self.mode_label.pack(anchor=tk.W, pady=3)

        session_frame = tk.Frame(info_frame, bg='#3d3d3d')
        session_frame.pack(side=tk.LEFT, padx=15, fill=tk.Y)
        tk.Label(session_frame, text="Session:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(anchor=tk.W)
        self.session_label = tk.Label(session_frame, text="Checking...", font=('Arial', 9), fg='#00ff00', bg='#3d3d3d')
        self.session_label.pack(anchor=tk.W)
        self.session_progress = ttk.Progressbar(session_frame, length=120, mode='determinate')
        self.session_progress.pack(anchor=tk.W, pady=3)

        adaptive_frame = tk.Frame(info_frame, bg='#3d3d3d')
        adaptive_frame.pack(side=tk.LEFT, padx=15, fill=tk.Y)
        tk.Label(adaptive_frame, text="Strategy Tier:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(anchor=tk.W)
        self.adaptive_label = tk.Label(adaptive_frame, text="Default", font=('Arial', 9), fg='#666666', bg='#3d3d3d')
        self.adaptive_label.pack(anchor=tk.W)

        drawdown_frame = tk.Frame(info_frame, bg='#3d3d3d')
        drawdown_frame.pack(side=tk.LEFT, padx=15, fill=tk.Y)
        tk.Label(drawdown_frame, text="Drawdown:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(anchor=tk.W)
        self.drawdown_label = tk.Label(drawdown_frame, text="Rp 0 / Rp 500,000", font=('Arial', 9), fg='#00ff00', bg='#3d3d3d')
        self.drawdown_label.pack(anchor=tk.W)
        self.drawdown_bar = ttk.Progressbar(drawdown_frame, length=120, mode='determinate')
        self.drawdown_bar.pack(anchor=tk.W, pady=3)

        log_frame = tk.Frame(dashboard, bg='#3d3d3d')
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)
        log_header = tk.Frame(log_frame, bg='#3d3d3d')
        log_header.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(log_header, text="Log Aktivitas:", font=('Arial', 9, 'bold'), fg='white', bg='#3d3d3d').pack(side=tk.LEFT)
        tk.Button(log_header, text="Clear Log", command=self.clear_log, bg='#555555', fg='white', font=('Arial', 8)).pack(side=tk.RIGHT)
        tk.Button(log_header, text="Archive Logs", command=self.open_archive_folder, bg='#555555', fg='white', font=('Arial', 8)).pack(side=tk.RIGHT, padx=3)

        self.log_text = scrolledtext.ScrolledText(log_frame, bg='#1e1e1e', fg='#00ff00', font=('Consolas', 9), height=8, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

        control_frame = tk.Frame(dashboard, bg='#2d2d2d', height=50)
        control_frame.pack(fill=tk.X, padx=5, pady=3)
        control_frame.pack_propagate(False)

        btn_frame = tk.Frame(control_frame, bg='#2d2d2d')
        btn_frame.pack(side=tk.LEFT, padx=10, pady=8)
        self.btn_start = tk.Button(btn_frame, text="START BOT", command=self.start_bot, bg='#00aa00', fg='white', font=('Arial', 10, 'bold'), width=10)
        self.btn_start.pack(side=tk.LEFT, padx=3)
        self.btn_stop = tk.Button(btn_frame, text="STOP BOT", command=self.stop_bot, bg='#aa0000', fg='white', font=('Arial', 10, 'bold'), width=10, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=3)
        self.btn_refresh = tk.Button(btn_frame, text="REFRESH", command=self.refresh_data, bg='#0066aa', fg='white', font=('Arial', 10, 'bold'), width=10)
        self.btn_refresh.pack(side=tk.LEFT, padx=3)
        self.btn_exit = tk.Button(btn_frame, text="EXIT", command=self.on_close, bg='#555555', fg='white', font=('Arial', 10, 'bold'), width=10)
        self.btn_exit.pack(side=tk.LEFT, padx=3)
        self.btn_test_conn = tk.Button(btn_frame, text="Cek Koneksi", command=self.test_connection_gui, bg='#aa6600', fg='white', font=('Arial', 9, 'bold'), width=12)
        self.btn_test_conn.pack(side=tk.LEFT, padx=3)

        self.force_close_var = tk.BooleanVar(value=False)
        tk.Checkbutton(control_frame, text="Force Close on Stop", variable=self.force_close_var, bg='#2d2d2d', fg='white', selectcolor='#2d2d2d', activebackground='#2d2d2d', activeforeground='white').pack(side=tk.LEFT, padx=5)

        self.paper_mode_var = tk.BooleanVar(value=False)
        self.paper_toggle = tk.Checkbutton(control_frame, text="Paper Mode", variable=self.paper_mode_var, command=self.toggle_paper_mode, bg='#2d2d2d', fg='#ffaa00', selectcolor='#2d2d2d', activebackground='#2d2d2d', activeforeground='#ffaa00', font=('Arial', 9, 'bold'))
        self.paper_toggle.pack(side=tk.LEFT, padx=5)

        quick_frame = tk.Frame(control_frame, bg='#2d2d2d')
        quick_frame.pack(side=tk.RIGHT, padx=10)
        tk.Label(quick_frame, text="Mode:", bg='#2d2d2d', fg='white', font=('Arial', 9)).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value=self.current_mode)
        ttk.Combobox(quick_frame, textvariable=self.mode_var, values=["BUY ONLY", "SELL ONLY", "BUY & SELL"], width=12, state='readonly').pack(side=tk.LEFT, padx=5)
        tk.Button(quick_frame, text="Apply", command=self.apply_quick_config, bg='#0066aa', fg='white', font=('Arial', 8)).pack(side=tk.LEFT, padx=5)

        self.update_mode_display()

    def setup_settings_tab(self):
        settings_frame = tk.Frame(self.notebook, bg='#1e1e1e')
        self.notebook.add(settings_frame, text="  Settings  ")

        canvas = tk.Canvas(settings_frame, bg='#1e1e1e', highlightthickness=0)
        vsb = ttk.Scrollbar(settings_frame, orient="vertical", command=canvas.yview)
        self.settings_inner = tk.Frame(canvas, bg='#1e1e1e')
        self.settings_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.settings_inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.settings_vars = {}
        pad = {'padx': 5, 'pady': 2}

        def section(parent, title):
            f = tk.LabelFrame(parent, text=title, bg='#2d2d2d', fg='#00ff00', font=('Arial', 9, 'bold'), padx=8, pady=4)
            f.pack(fill=tk.X, padx=5, pady=3)
            return f

        def field(parent, label, key, default="", row=0, width=22, colspan=1):
            tk.Label(parent, text=label, bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=row, column=0, sticky=tk.W, **pad)
            var = tk.StringVar(value=str(default))
            self.settings_vars[key] = var
            tk.Entry(parent, textvariable=var, width=width, bg='#1e1e1e', fg='#00ff00', insertbackground='white', font=('Arial', 8)).grid(row=row, column=1, columnspan=colspan, sticky=tk.EW, **pad)
            return var

        def combo_field(parent, label, key, values, default="", row=0):
            tk.Label(parent, text=label, bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=row, column=0, sticky=tk.W, **pad)
            var = tk.StringVar(value=str(default))
            self.settings_vars[key] = var
            ttk.Combobox(parent, textvariable=var, values=values, width=14, state='readonly').grid(row=row, column=1, sticky=tk.W, **pad)
            return var

        def check_field(parent, label, key, default=False, row=0, col=0):
            var = tk.BooleanVar(value=default)
            self.settings_vars[key] = var
            tk.Checkbutton(parent, text=label, variable=var, bg='#2d2d2d', fg='white', selectcolor='#2d2d2d', activebackground='#2d2d2d', activeforeground='white', font=('Arial', 8)).grid(row=row, column=col, columnspan=2, sticky=tk.W, **pad)
            return var

        row_container = tk.Frame(self.settings_inner, bg='#1e1e1e')
        row_container.pack(fill=tk.X, padx=5)

        left_col = tk.Frame(row_container, bg='#1e1e1e')
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_col = tk.Frame(row_container, bg='#1e1e1e')
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ex = section(left_col, "Exchange")
        r = 0
        combo_field(ex, "Exchange:", "exchange_name", ["indodax", "tokocrypto"], self.config.get('exchange', {}).get('name', 'indodax'), r); r += 1
        field(ex, "API Key:", "api_key", self.config.get('exchange', {}).get('api_key', ''), r); r += 1
        field(ex, "API Secret:", "api_secret", self.config.get('exchange', {}).get('api_secret', ''), r); r += 1

        tf = section(left_col, "Timeframe")
        r = 0
        combo_field(tf, "Entry TF:", "entry_tf", ["M1", "M5", "M15", "M30"], self.config.get('timeframe', {}).get('entry', 'M5'), r); r += 1
        combo_field(tf, "Trend TF:", "trend_tf", ["H1", "H4", "D1"], self.config.get('timeframe', {}).get('trend', 'H4'), r); r += 1

        st = section(left_col, "Strategy")
        r = 0
        field(st, "EMA Fast:", "ema_fast", self.config.get('strategy', {}).get('ema_fast', 50), r); r += 1
        field(st, "EMA Slow:", "ema_slow", self.config.get('strategy', {}).get('ema_slow', 200), r); r += 1
        field(st, "RSI Period:", "rsi_period", self.config.get('strategy', {}).get('rsi_period', 14), r); r += 1
        combo_field(st, "Divergence Ind:", "divergence_ind", ["RSI", "MACD"], self.config.get('strategy', {}).get('divergence_indicator', 'RSI'), r); r += 1
        field(st, "Doji Threshold:", "doji_threshold", self.config.get('strategy', {}).get('doji_threshold', 0.001), r); r += 1
        check_field(st, "Wait Candle Close", "wait_candle_close", self.config.get('strategy', {}).get('wait_for_candle_close', False), r); r += 1

        dd = section(left_col, "Daily Drawdown")
        r = 0
        check_field(dd, "Enable", "dd_enabled", self.config.get('daily_drawdown', {}).get('enabled', True), r); r += 1
        field(dd, "Max Loss %:", "dd_max_percent", self.config.get('daily_drawdown', {}).get('max_loss_percent', 5), r); r += 1
        field(dd, "Max Loss IDR:", "dd_max_idr", self.config.get('daily_drawdown', {}).get('max_loss_idr', 500000), r); r += 1
        field(dd, "Reset Time:", "dd_reset_time", self.config.get('daily_drawdown', {}).get('reset_time', '00:00'), r); r += 1

        tg = section(left_col, "Telegram")
        r = 0
        check_field(tg, "Enable", "tg_enabled", self.config.get('telegram', {}).get('enabled', False), r); r += 1
        field(tg, "Bot Token:", "tg_token", self.config.get('telegram', {}).get('token', ''), r); r += 1
        field(tg, "Chat ID:", "tg_chat_id", self.config.get('telegram', {}).get('chat_id', ''), r); r += 1
        check_field(tg, "Receive Cmds", "tg_receive", self.config.get('telegram', {}).get('receive_commands', True), r); r += 1

        rm = section(right_col, "Risk Management")
        r = 0
        field(rm, "Auto Lot (IDR):", "auto_lot_balance", self.config.get('risk_management', {}).get('auto_lot_balance', 10000000), r); r += 1
        field(rm, "Risk Multiplier:", "risk_multiplier", self.config.get('risk_management', {}).get('risk_multiplier', 1), r); r += 1
        field(rm, "ATR Period:", "atr_period", self.config.get('risk_management', {}).get('atr_period', 14), r); r += 1
        field(rm, "ATR Multiplier:", "atr_multiplier", self.config.get('risk_management', {}).get('atr_multiplier', 1.5), r); r += 1
        field(rm, "Min R:R Ratio:", "min_rr_ratio", self.config.get('risk_management', {}).get('min_rr_ratio', 2.0), r); r += 1
        field(rm, "Max Positions:", "max_positions", self.config.get('risk_management', {}).get('max_positions', 3), r); r += 1
        field(rm, "Pyramiding %:", "pyramiding_trigger", self.config.get('risk_management', {}).get('pyramiding_trigger_percent', 1.0), r); r += 1
        check_field(rm, "Allow Multi Per Pair", "allow_multi_pair", self.config.get('risk_management', {}).get('allow_multiple_per_pair', False), r); r += 1

        ts = section(right_col, "Trading Session")
        r = 0
        check_field(ts, "Enable", "ts_enabled", self.config.get('trading_session', {}).get('enabled', True), r); r += 1
        field(ts, "Start Time:", "ts_start", self.config.get('trading_session', {}).get('start_time', '08:00'), r); r += 1
        field(ts, "End Time:", "ts_end", self.config.get('trading_session', {}).get('end_time', '22:00'), r); r += 1

        mh = section(right_col, "Max Holding Time")
        r = 0
        check_field(mh, "Enable", "mh_enabled", self.config.get('max_holding_time', {}).get('enabled', True), r); r += 1
        field(mh, "Max Hours:", "mh_hours", self.config.get('max_holding_time', {}).get('max_hours', 24), r); r += 1
        field(mh, "Warning Min:", "mh_warning", self.config.get('max_holding_time', {}).get('notification_warning_minutes', 60), r); r += 1

        bt = section(right_col, "Backtest")
        r = 0
        field(bt, "Max Candles:", "bt_max_candles", self.config.get('backtest', {}).get('max_candles', 5000), r); r += 1

        wh = section(right_col, "Webhook (Optional)")
        r = 0
        check_field(wh, "Enable", "wh_enabled", self.config.get('webhook', {}).get('enabled', False), r); r += 1
        field(wh, "Port:", "wh_port", self.config.get('webhook', {}).get('port', 5000), r); r += 1
        field(wh, "Symbols:", "wh_symbols", self.config.get('webhook', {}).get('allowed_symbols', ''), r); r += 1

        row_container2 = tk.Frame(self.settings_inner, bg='#1e1e1e')
        row_container2.pack(fill=tk.X, padx=5)

        pr = section(row_container2, "Trading Pairs")
        r = 0
        pairs_str = ", ".join(self.config.get('trading_pairs', []))
        field(pr, "Pairs (comma):", "trading_pairs", pairs_str, r, width=50, colspan=3); r += 1
        tk.Label(pr, text="Kosongkan = otomatis semua pair IDR", bg='#2d2d2d', fg='#888888', font=('Arial', 8)).grid(row=r, column=0, columnspan=4, sticky=tk.W, **pad); r += 1
        self.pairs_frame = tk.Frame(pr, bg='#2d2d2d')
        self.pairs_frame.grid(row=r, column=0, columnspan=4, sticky=tk.W, **pad); r += 1
        tk.Button(pr, text="Scan Pairs", command=self.scan_pairs_for_settings, bg='#0066aa', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, **pad)

        btn_frame = tk.Frame(self.settings_inner, bg='#1e1e1e')
        btn_frame.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(btn_frame, text="SAVE SETTINGS", command=self.save_settings, bg='#00aa00', fg='white', font=('Arial', 10, 'bold'), width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="RESET DEFAULT", command=self.reset_settings, bg='#aa6600', fg='white', font=('Arial', 10, 'bold'), width=15).pack(side=tk.LEFT, padx=5)

    def setup_charts_tab(self):
        charts_frame = tk.Frame(self.notebook, bg='#1e1e1e')
        self.notebook.add(charts_frame, text="  Charts  ")

        toolbar = tk.Frame(charts_frame, bg='#2d2d2d')
        toolbar.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(toolbar, text="Pair:", bg='#2d2d2d', fg='white', font=('Arial', 9)).pack(side=tk.LEFT, padx=5)
        self.chart_pair_var = tk.StringVar(value="btc_idr")
        self.chart_pair_menu = ttk.Combobox(toolbar, textvariable=self.chart_pair_var, values=self.trading_pairs, width=15)
        self.chart_pair_menu.pack(side=tk.LEFT, padx=3)
        tk.Label(toolbar, text="TF:", bg='#2d2d2d', fg='white', font=('Arial', 9)).pack(side=tk.LEFT, padx=5)
        self.chart_tf_var = tk.StringVar(value="M5")
        ttk.Combobox(toolbar, textvariable=self.chart_tf_var, values=["M1", "M5", "M15", "M30", "H1", "H4", "D1"], width=8).pack(side=tk.LEFT, padx=3)
        tk.Button(toolbar, text="Load Chart", command=self.load_chart, bg='#0066aa', fg='white', font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=10)
        tk.Button(toolbar, text="Refresh", command=self.refresh_chart, bg='#555555', fg='white', font=('Arial', 9)).pack(side=tk.LEFT, padx=3)

        chart_container = tk.Frame(charts_frame, bg='#0a0a0a')
        chart_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

        header_frame = tk.Frame(chart_container, bg='#2d2d2d')
        header_frame.pack(fill=tk.X)
        headers = [("Time", 16), ("O", 10), ("H", 10), ("L", 10), ("C", 10), ("EMA50", 10), ("EMA200", 10), ("Vol", 12)]
        for text, width in headers:
            tk.Label(header_frame, text=text, bg='#2d2d2d', fg='#ffaa00', font=('Consolas', 9, 'bold'), width=width, anchor=tk.W).pack(side=tk.LEFT, padx=1)

        self.chart_text = scrolledtext.ScrolledText(chart_container, bg='#0a0a0a', fg='#00ff00', font=('Consolas', 9), height=25, wrap=tk.NONE)
        self.chart_text.pack(fill=tk.BOTH, expand=True)
        self.chart_text.insert(tk.END, "\n  Select pair + TF, click 'Load Chart' to view data.\n  If no data appears, ensure API Key is set in Settings.\n")

    def setup_backtest_tab(self):
        bt_frame = tk.Frame(self.notebook, bg='#1e1e1e')
        self.notebook.add(bt_frame, text="  Backtest  ")

        top = tk.Frame(bt_frame, bg='#1e1e1e')
        top.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

        left = tk.LabelFrame(top, text="Parameters", bg='#2d2d2d', fg='#00ff00', font=('Arial', 9, 'bold'), padx=10, pady=5)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=3)

        r = 0
        tk.Label(left, text="Pair:", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_pair_var = tk.StringVar(value="btc_idr")
        ttk.Combobox(left, textvariable=self.bt_pair_var, values=self.trading_pairs, width=15).grid(row=r, column=1, padx=3, pady=2); r += 1

        tk.Label(left, text="Start Date:", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_start_var = tk.StringVar(value="2024-01-01")
        tk.Entry(left, textvariable=self.bt_start_var, width=15, bg='#1e1e1e', fg='#00ff00', font=('Arial', 8)).grid(row=r, column=1, padx=3, pady=2); r += 1

        tk.Label(left, text="End Date:", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_end_var = tk.StringVar(value="2025-12-31")
        tk.Entry(left, textvariable=self.bt_end_var, width=15, bg='#1e1e1e', fg='#00ff00', font=('Arial', 8)).grid(row=r, column=1, padx=3, pady=2); r += 1

        tk.Label(left, text="Timeframe:", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_tf_var = tk.StringVar(value="M5")
        ttk.Combobox(left, textvariable=self.bt_tf_var, values=["M1", "M5", "M15", "M30", "H1", "H4"], width=12).grid(row=r, column=1, padx=3, pady=2); r += 1

        tk.Label(left, text="Balance (IDR):", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_balance_var = tk.StringVar(value="100000000")
        tk.Entry(left, textvariable=self.bt_balance_var, width=15, bg='#1e1e1e', fg='#00ff00', font=('Arial', 8)).grid(row=r, column=1, padx=3, pady=2); r += 1

        tk.Label(left, text="Slippage %:", bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=r, column=0, sticky=tk.W, padx=3, pady=2)
        self.bt_slip_var = tk.StringVar(value="0.1")
        tk.Entry(left, textvariable=self.bt_slip_var, width=15, bg='#1e1e1e', fg='#00ff00', font=('Arial', 8)).grid(row=r, column=1, padx=3, pady=2); r += 1

        right = tk.Frame(top, bg='#1e1e1e')
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)

        self.bt_stats_frame = tk.LabelFrame(right, text="Results", bg='#2d2d2d', fg='#00ff00', font=('Arial', 9, 'bold'), padx=10, pady=5)
        self.bt_stats_frame.pack(fill=tk.BOTH, expand=True)

        self.bt_stats_labels = {}
        stats = [("Total Return:", "return"), ("Total Profit:", "profit"), ("Win Rate:", "winrate"),
                 ("Total Trades:", "trades"), ("Max Drawdown:", "drawdown"), ("Profit Factor:", "pf"),
                 ("Sharpe Ratio:", "sharpe"), ("Best Trade:", "best"), ("Worst Trade:", "worst")]
        for i, (label, key) in enumerate(stats):
            tk.Label(self.bt_stats_frame, text=label, bg='#2d2d2d', fg='white', font=('Arial', 8)).grid(row=i, column=0, sticky=tk.W, padx=3, pady=1)
            lbl = tk.Label(self.bt_stats_frame, text="-", bg='#2d2d2d', fg='#00ff00', font=('Arial', 8, 'bold'))
            lbl.grid(row=i, column=1, sticky=tk.W, padx=3, pady=1)
            self.bt_stats_labels[key] = lbl

        btn_frame = tk.Frame(bt_frame, bg='#2d2d2d')
        btn_frame.pack(fill=tk.X, padx=5, pady=3)
        self.btn_bt_run = tk.Button(btn_frame, text="Run Backtest", command=self.run_backtest_gui, bg='#00aa00', fg='white', font=('Arial', 9, 'bold'), width=15)
        self.btn_bt_run.pack(side=tk.LEFT, padx=5, pady=3)
        self.btn_bt_export = tk.Button(btn_frame, text="Export CSV", command=self.export_backtest_csv, bg='#0066aa', fg='white', font=('Arial', 9), width=12, state=tk.DISABLED)
        self.btn_bt_export.pack(side=tk.LEFT, padx=5, pady=3)
        self.bt_progress = ttk.Progressbar(btn_frame, length=200, mode='determinate')
        self.bt_progress.pack(side=tk.LEFT, padx=10, pady=3)

        table_frame = tk.Frame(bt_frame, bg='#2d2d2d')
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)
        cols = ("#", "Date", "Side", "Entry", "Exit", "PnL IDR", "PnL %")
        self.bt_tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=8)
        for c in cols:
            self.bt_tree.heading(c, text=c)
            self.bt_tree.column(c, width=80 if c != "#" else 30)
        self.bt_tree.pack(fill=tk.BOTH, expand=True)
        self.bt_results_data = None

    def setup_paper_tab(self):
        paper_frame = tk.Frame(self.notebook, bg='#1e1e1e')
        self.notebook.add(paper_frame, text="  Paper Trading  ")

        banner = tk.Frame(paper_frame, bg='#aa8800', height=35)
        banner.pack(fill=tk.X, padx=5, pady=3)
        banner.pack_propagate(False)
        tk.Label(banner, text="PAPER TRADING MODE (UANG VIRTUAL)", bg='#aa8800', fg='white', font=('Arial', 11, 'bold')).pack(pady=6)

        status_frame = tk.Frame(paper_frame, bg='#2d2d2d')
        status_frame.pack(fill=tk.X, padx=5, pady=3)

        for i, (label, key) in enumerate([("Balance:", "balance"), ("Equity:", "equity"), ("Floating PnL:", "floating"), ("Total PnL:", "total_pnl")]):
            tk.Label(status_frame, text=label, bg='#2d2d2d', fg='white', font=('Arial', 9, 'bold')).grid(row=0, column=i*2, padx=10, pady=3, sticky=tk.W)
            lbl = tk.Label(status_frame, text="Rp 0", bg='#2d2d2d', fg='#00ff00', font=('Arial', 9))
            lbl.grid(row=0, column=i*2+1, padx=3, pady=3, sticky=tk.W)
            setattr(self, f'paper_{key}_label', lbl)

        ctrl_frame = tk.Frame(paper_frame, bg='#2d2d2d')
        ctrl_frame.pack(fill=tk.X, padx=5, pady=3)

        self.btn_paper_start = tk.Button(ctrl_frame, text="Start Paper Trading", command=self.start_paper_trading, bg='#00aa00', fg='white', font=('Arial', 9, 'bold'), width=18)
        self.btn_paper_start.pack(side=tk.LEFT, padx=5, pady=3)
        self.btn_paper_stop = tk.Button(ctrl_frame, text="Stop Paper Trading", command=self.stop_paper_trading, bg='#aa0000', fg='white', font=('Arial', 9, 'bold'), width=18, state=tk.DISABLED)
        self.btn_paper_stop.pack(side=tk.LEFT, padx=5, pady=3)
        self.btn_paper_reset = tk.Button(ctrl_frame, text="Reset Account", command=self.reset_paper_account, bg='#aa6600', fg='white', font=('Arial', 9), width=15)
        self.btn_paper_reset.pack(side=tk.LEFT, padx=5, pady=3)

        tk.Label(ctrl_frame, text="Set Balance:", bg='#2d2d2d', fg='white', font=('Arial', 8)).pack(side=tk.LEFT, padx=(15, 3))
        self.paper_set_bal_var = tk.StringVar(value="100000000")
        tk.Entry(ctrl_frame, textvariable=self.paper_set_bal_var, width=12, bg='#1e1e1e', fg='#00ff00', font=('Arial', 8)).pack(side=tk.LEFT, padx=3)
        tk.Button(ctrl_frame, text="Apply", command=self.apply_paper_balance, bg='#0066aa', fg='white', font=('Arial', 8)).pack(side=tk.LEFT, padx=3)

        tables_frame = tk.Frame(paper_frame, bg='#1e1e1e')
        tables_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

        open_frame = tk.LabelFrame(tables_frame, text="Open Positions", bg='#2d2d2d', fg='#00ff00', font=('Arial', 9, 'bold'))
        open_frame.pack(fill=tk.X, pady=2)
        open_cols = ("Symbol", "Side", "Entry", "Current", "Qty", "PnL IDR", "PnL %")
        self.paper_open_tree = ttk.Treeview(open_frame, columns=open_cols, show='headings', height=4)
        for c in open_cols:
            self.paper_open_tree.heading(c, text=c)
            self.paper_open_tree.column(c, width=100 if c != "Qty" else 70)
        self.paper_open_tree.pack(fill=tk.X, padx=3, pady=3)

        hist_frame = tk.LabelFrame(tables_frame, text="Trade History", bg='#2d2d2d', fg='#00ff00', font=('Arial', 9, 'bold'))
        hist_frame.pack(fill=tk.BOTH, expand=True, pady=2)
        hist_cols = ("#", "Date", "Symbol", "Side", "Entry", "Exit", "PnL IDR", "Reason")
        self.paper_hist_tree = ttk.Treeview(hist_frame, columns=hist_cols, show='headings', height=6)
        for c in hist_cols:
            self.paper_hist_tree.heading(c, text=c)
            self.paper_hist_tree.column(c, width=90 if c not in ("#", "Reason") else 50)
        self.paper_hist_tree.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

    def append_log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_line = f"[{timestamp}] {message}\n"
        self.log_text.insert(tk.END, log_line)
        self.log_text.see(tk.END)
        max_lines = self.config.get('gui', {}).get('log_max_lines', 1000)
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > max_lines:
            self.log_text.delete('1.0', f'{lines - max_lines}.0')

    def show_api_error(self, message):
        self.api_error_label.config(text=f"[ERROR] {message}")

    def clear_log(self):
        self.log_text.delete('1.0', tk.END)
        self.api_error_label.config(text="")

    def open_archive_folder(self):
        archive_dir = self.logger.get_archive_dir()
        os.makedirs(archive_dir, exist_ok=True)
        try:
            subprocess.Popen(f'explorer "{archive_dir}"')
        except Exception:
            messagebox.showinfo("Archive Folder", f"Logs archived at:\n{archive_dir}")

    def test_connection_gui(self):
        self.btn_test_conn.config(state=tk.DISABLED, text="Testing...")
        def do_test():
            try:
                result = self.exchange.test_connection()
                self.root.after(0, lambda: self._show_connection_result(result))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
                self.root.after(0, lambda: self.btn_test_conn.config(state=tk.NORMAL, text="Cek Koneksi"))
        threading.Thread(target=do_test, daemon=True).start()

    def _show_connection_result(self, result):
        self.btn_test_conn.config(state=tk.NORMAL, text="Cek Koneksi")
        status = result.get('overall_status', 'UNKNOWN')
        if status == "CONNECTED":
            icon = "CONNECTED"
            color = "green"
        elif status == "PARTIAL":
            icon = "PARTIAL (No API Key)"
            color = "orange"
        else:
            icon = "DISCONNECTED"
            color = "red"

        msg = f"Overall Status: {icon}\n\n"
        msg += f"Public API: {'OK' if result['public']['status'] == 'ok' else 'ERROR'}\n"
        msg += f"  {result['public']['message']}\n\n"
        msg += f"Private API: {'OK' if result['private']['status'] == 'ok' else result['private']['status']}\n"
        msg += f"  {result['private']['message']}\n\n"
        msg += f"Trade Permission: {'OK' if result['trade_permission']['status'] == 'ok' else result['trade_permission']['status']}\n"
        msg += f"  {result['trade_permission']['message']}"

        win = tk.Toplevel(self.root)
        win.title("Connection Test Result")
        win.geometry("450x350")
        win.configure(bg='#1e1e1e')

        tk.Label(win, text=f"Status: {icon}", bg='#1e1e1e', fg=color, font=('Arial', 14, 'bold')).pack(pady=10)
        tk.Label(win, text=msg, bg='#1e1e1e', fg='white', font=('Consolas', 9), justify=tk.LEFT, anchor=tk.W).pack(padx=20, fill=tk.X)

        if status != "CONNECTED":
            tk.Button(win, text="Open Settings", command=lambda: [win.destroy(), self.notebook.select(1)], bg='#0066aa', fg='white', font=('Arial', 9)).pack(pady=10)
        tk.Button(win, text="Close", command=win.destroy, bg='#555555', fg='white', font=('Arial', 9)).pack(pady=5)

    def toggle_paper_mode(self):
        self.paper_mode = self.paper_mode_var.get()
        if self.paper_mode:
            self.status_label.config(text="Paper Mode", fg='#ffaa00')
            self.append_log("Switched to Paper Trading Mode")
        else:
            self.status_label.config(text="Live Mode", fg='#00ff00')
            self.append_log("Switched to Live Trading Mode")

    def run_backtest_gui(self):
        self.btn_bt_run.config(state=tk.DISABLED)
        self.bt_progress['value'] = 0

        def do_backtest():
            try:
                pair = self.bt_pair_var.get()
                tf = self.bt_tf_var.get()
                balance = int(self.bt_balance_var.get())
                max_candles = self.config.get('backtest', {}).get('max_candles', 5000)

                self.root.after(0, lambda: self.bt_stats_labels['return'].config(text="Running..."))
                klines = self.exchange.get_klines(pair, tf, max_candles)
                if not klines:
                    self.root.after(0, lambda: messagebox.showerror("Error", "No data available. Check API Key."))
                    self.root.after(0, lambda: self.btn_bt_run.config(state=tk.NORMAL))
                    return

                self.root.after(0, lambda: self.bt_progress.configure(value=30))

                import numpy as np
                import pandas as pd
                config_copy = dict(self.config)
                config_copy['risk_management'] = dict(self.config['risk_management'])
                config_copy['risk_management']['auto_lot_balance'] = balance // 10

                bt = Backtester(config_copy)
                result = bt.run_backtest(klines, klines, balance)

                self.root.after(0, lambda: self.bt_progress.configure(value=90))

                self.bt_results_data = result
                self.root.after(0, lambda: self._display_backtest_results(result))
                self.root.after(0, lambda: self.btn_bt_export.config(state=tk.NORMAL))
                self.root.after(0, lambda: self.bt_progress.configure(value=100))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Backtest Error", str(e)))
            finally:
                self.root.after(0, lambda: self.btn_bt_run.config(state=tk.NORMAL))

        threading.Thread(target=do_backtest, daemon=True).start()

    def _display_backtest_results(self, result):
        profit_color = '#00ff00' if result['total_pnl'] >= 0 else '#ff0000'
        self.bt_stats_labels['return'].config(text=f"{result['roi']:.2f}%", fg=profit_color)
        self.bt_stats_labels['profit'].config(text=f"Rp {result['total_pnl']:,.0f}", fg=profit_color)
        self.bt_stats_labels['winrate'].config(text=f"{result['win_rate']:.1f}%")
        self.bt_stats_labels['trades'].config(text=str(result['total_trades']))
        self.bt_stats_labels['drawdown'].config(text=f"{result['max_drawdown']:.2f}%", fg='#ff0000')
        self.bt_stats_labels['pf'].config(text=f"{result['profit_factor']:.2f}")
        self.bt_stats_labels['sharpe'].config(text=f"{result['sharpe_ratio']:.2f}")
        self.bt_stats_labels['best'].config(text=f"Rp {result.get('avg_win', 0):,.0f}", fg='#00ff00')
        self.bt_stats_labels['worst'].config(text=f"Rp {result.get('avg_loss', 0):,.0f}", fg='#ff0000')

        for item in self.bt_tree.get_children():
            self.bt_tree.delete(item)

        for i, trade in enumerate(result.get('trades', [])[:20], 1):
            ts = datetime.fromtimestamp(trade.get('entry_time', 0) / 1000).strftime('%Y-%m-%d %H:%M') if isinstance(trade.get('entry_time', 0), (int, float)) else str(trade.get('entry_time', ''))[:16]
            pnl = trade.get('pnl', 0)
            pnl_pct = (pnl / trade['entry_price'] * 100) if trade['entry_price'] > 0 else 0
            pnl_color = '#00ff00' if pnl >= 0 else '#ff0000'
            item_id = self.bt_tree.insert('', 'end', values=(i, ts[:10], trade['direction'], f"{trade['entry_price']:,.0f}", f"{trade.get('exit_price', 0):,.0f}", f"{pnl:,.0f}", f"{pnl_pct:.2f}%"))
            self.bt_tree.tag_configure(item_id, foreground=pnl_color)

    def export_backtest_csv(self):
        if not self.bt_results_data:
            return
        try:
            import csv
            filepath = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")], title="Export Backtest Results")
            if not filepath:
                return
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["#", "Direction", "Entry Price", "Exit Price", "PnL"])
                for i, t in enumerate(self.bt_results_data.get('trades', []), 1):
                    writer.writerow([i, t['direction'], t['entry_price'], t.get('exit_price', 0), t.get('pnl', 0)])
            self.append_log(f"Backtest exported to {filepath}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def start_paper_trading(self):
        self.paper_running = True
        self.btn_paper_start.config(state=tk.DISABLED)
        self.btn_paper_stop.config(state=tk.NORMAL)
        self.paper_mode_var.set(True)
        self.toggle_paper_mode()
        self.append_log("Paper Trading started")
        self.paper_thread = threading.Thread(target=self._paper_trading_loop, daemon=True)
        self.paper_thread.start()

    def stop_paper_trading(self):
        self.paper_running = False
        self.btn_paper_start.config(state=tk.NORMAL)
        self.btn_paper_stop.config(state=tk.DISABLED)
        self.append_log("Paper Trading stopped")

    def _paper_trading_loop(self):
        while self.paper_running:
            try:
                if not self.time_manager.is_within_session():
                    time.sleep(30)
                    continue

                self.monitor_paper_sl_tp()

                for pair in self.trading_pairs:
                    if not self.paper_running:
                        break
                    signal = self.check_signal(pair)
                    if signal:
                        self.execute_signal(pair, signal)
                    time.sleep(1)

                open_trades = self.paper_engine.get_open_trades()
                current_prices = {}
                for trade in open_trades:
                    symbol = trade[1]
                    if symbol not in current_prices:
                        try:
                            klines = self.exchange.get_klines(symbol, 'M5', 1)
                            if klines:
                                current_prices[symbol] = klines[-1]['close']
                        except Exception:
                            pass

                equity = self.paper_engine.get_equity(open_trades, current_prices)
                balance = self.paper_engine.get_balance()
                floating = equity - balance

                self.root.after(0, lambda b=balance, e=equity, f=floating: self._update_paper_display(b, e, f))
                time.sleep(5)
            except Exception as e:
                self.append_log(f"Paper trading error: {e}")
                time.sleep(10)

    def monitor_paper_sl_tp(self):
        try:
            open_trades = self.paper_engine.get_open_trades()
            for trade in open_trades:
                trade_id = trade[0]
                symbol = trade[1]
                side = trade[2]
                quantity = trade[3]
                entry_price = trade[4]
                sl_price = trade[12] if len(trade) > 12 else 0
                tp_price = trade[13] if len(trade) > 13 else 0

                if sl_price == 0 and tp_price == 0:
                    continue

                try:
                    klines = self.exchange.get_klines(symbol, 'M5', 1)
                    if not klines:
                        continue
                    current_price = klines[-1]['close']
                except Exception:
                    continue

                exit_reason = ""
                should_close = False

                if side == 'BUY':
                    if sl_price > 0 and current_price <= sl_price:
                        exit_reason = "sl"
                        should_close = True
                    elif tp_price > 0 and current_price >= tp_price:
                        exit_reason = "tp"
                        should_close = True
                else:
                    if sl_price > 0 and current_price >= sl_price:
                        exit_reason = "sl"
                        should_close = True
                    elif tp_price > 0 and current_price <= tp_price:
                        exit_reason = "tp"
                        should_close = True

                if should_close:
                    try:
                        pnl = self.paper_engine.close_position(trade_id, current_price, exit_reason)
                        if pnl is not None:
                            msg = f"Paper {'STOP LOSS' if exit_reason == 'sl' else 'TAKE PROFIT'}: {symbol} @ Rp {current_price:,.2f} | PnL: Rp {pnl:,.2f}"
                            self.append_log(msg)
                    except Exception:
                        continue

        except Exception as e:
            self.append_log(f"[WARNING] Paper SL/TP monitor error: {e}")

    def _update_paper_display(self, balance, equity, floating):
        self.paper_balance_label.config(text=f"Rp {balance:,.0f}")
        self.paper_equity_label.config(text=f"Rp {equity:,.0f}")
        self.paper_floating_label.config(text=f"Rp {floating:,.0f}", fg='#00ff00' if floating >= 0 else '#ff0000')

        for item in self.paper_open_tree.get_children():
            self.paper_open_tree.delete(item)

        open_trades = self.paper_engine.get_open_trades()
        for trade in open_trades:
            symbol, side, qty, entry_price = trade[1], trade[2], trade[3], trade[4]
            try:
                klines = self.exchange.get_klines(symbol, 'M5', 1)
                curr = klines[-1]['close'] if klines else entry_price
            except Exception:
                curr = entry_price
            pnl = (curr - entry_price) * qty if side == 'BUY' else (entry_price - curr) * qty
            pnl_pct = (pnl / (entry_price * qty) * 100) if entry_price * qty > 0 else 0
            self.paper_open_tree.insert('', 'end', values=(symbol, side, f"{entry_price:,.0f}", f"{curr:,.0f}", f"{qty:.6f}", f"{pnl:,.0f}", f"{pnl_pct:.2f}%"))

        self._refresh_paper_history()

    def _refresh_paper_history(self):
        for item in self.paper_hist_tree.get_children():
            self.paper_hist_tree.delete(item)
        closed = self.paper_engine.get_closed_trades(20)
        for i, trade in enumerate(closed, 1):
            ts = str(trade[12])[:10] if trade[12] else ""
            pnl = trade[7]
            reason = trade[11] or "-"
            self.paper_hist_tree.insert('', 'end', values=(i, ts, trade[1], trade[2], f"{trade[4]:,.0f}", f"{trade[9]:,.0f}" if trade[9] else "-", f"{pnl:,.0f}", reason))

    def reset_paper_account(self):
        if messagebox.askyesno("Reset Account", "Reset virtual account to initial balance? All history will be deleted."):
            balance = int(self.paper_set_bal_var.get())
            self.paper_engine.reset_account(balance)
            self.append_log(f"Paper account reset to Rp {balance:,.0f}")
            self._refresh_paper_history()

    def apply_paper_balance(self):
        try:
            balance = int(self.paper_set_bal_var.get())
            self.paper_engine.set_balance(balance)
            self.append_log(f"Paper balance set to Rp {balance:,.0f}")
        except ValueError:
            messagebox.showerror("Error", "Invalid balance amount")

    def update_mode_display(self):
        mode = self.current_mode
        if mode == "BUY ONLY":
            self.mode_label.config(text="BUY ONLY", bg='#00aa00')
        elif mode == "SELL ONLY":
            self.mode_label.config(text="SELL ONLY", bg='#aa0000')
        else:
            self.mode_label.config(text="BUY & SELL", bg='#666666')

    def update_session_display(self):
        status, info = self.time_manager.get_session_status()
        if status == "ACTIVE":
            self.session_label.config(text=f"Active {info}", fg='#00ff00')
            remaining = self.time_manager.get_session_remaining_minutes()
            self.session_progress['value'] = (remaining / 1440) * 100 if remaining > 0 else 0
        elif status == "PAUSED":
            self.session_label.config(text=f"Paused {info}", fg='#ff0000')
            self.session_progress['value'] = 0
        else:
            self.session_label.config(text="Disabled", fg='#666666')
            self.session_progress['value'] = 100

    def update_adaptive_display(self):
        if not self.adaptive.enabled:
            self.adaptive_label.config(text="Disabled", fg='#666666')
            return
        idr = self.balances.get('idr', 0)
        tier_info = self.adaptive.get_tier_info(idr)
        self.adaptive_label.config(text=tier_info['name'], fg=tier_info['color'])

    def show_first_run_message(self):
        app_dir = self.get_app_dir()
        config_path = os.path.join(app_dir, 'config.json')
        messagebox.showinfo("First Run - KAMSIADI.Inc Bot", f"Config file created:\n{config_path}\n\nEdit this file to set your API keys, then restart the bot.")

    def apply_quick_config(self):
        self.current_mode = self.mode_var.get()
        self.config['trading_mode'] = self.current_mode
        self.save_config()
        self.update_mode_display()
        self.append_log(f"Mode changed to: {self.current_mode}")

    def scan_pairs_for_settings(self):
        try:
            self.append_log("Scanning pairs for settings...")
            tickers = self.exchange.get_tickers()
            self.all_pairs = [p for p in tickers if p.endswith('_idr') or p.endswith('IDR')]
            self.all_pairs.sort()

            for widget in self.pairs_frame.winfo_children():
                widget.destroy()

            self.pair_check_vars = {}
            config_pairs = self.config.get('trading_pairs', [])
            cols = 3
            for i, pair in enumerate(self.all_pairs[:60]):
                var = tk.BooleanVar(value=(not config_pairs or pair in config_pairs))
                self.pair_check_vars[pair] = var
                cb = tk.Checkbutton(self.pairs_frame, text=pair, variable=var, bg='#2d2d2d', fg='white', selectcolor='#2d2d2d', activebackground='#2d2d2d', activeforeground='white', font=('Arial', 8))
                cb.grid(row=i // cols, column=i % cols, sticky=tk.W, padx=5, pady=1)

            self.append_log(f"Found {len(self.all_pairs)} pairs")
        except Exception as e:
            self.append_log(f"Error scanning pairs: {e}")

    def save_settings(self):
        v = self.settings_vars

        def safe_int(key, default=0):
            try:
                return int(v[key].get())
            except (ValueError, KeyError):
                return default

        def safe_float(key, default=0.0):
            try:
                return float(v[key].get())
            except (ValueError, KeyError):
                return default

        self.config['exchange'] = {'name': v['exchange_name'].get(), 'api_key': v['api_key'].get(), 'api_secret': v['api_secret'].get()}
        self.config['timeframe'] = {'entry': v['entry_tf'].get(), 'trend': v['trend_tf'].get()}
        self.config['strategy'] = {'ema_fast': safe_int('ema_fast', 50), 'ema_slow': safe_int('ema_slow', 200), 'rsi_period': safe_int('rsi_period', 14), 'divergence_indicator': v['divergence_ind'].get(), 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'doji_threshold': safe_float('doji_threshold', 0.001), 'wait_for_candle_close': v.get('wait_candle_close', tk.BooleanVar()).get() if 'wait_candle_close' in v else False}
        self.config['risk_management'] = {'auto_lot_balance': safe_int('auto_lot_balance', 10000000), 'risk_multiplier': safe_float('risk_multiplier', 1), 'atr_period': safe_int('atr_period', 14), 'atr_multiplier': safe_float('atr_multiplier', 1.5), 'min_rr_ratio': safe_float('min_rr_ratio', 2.0), 'max_positions': safe_int('max_positions', 3), 'pyramiding_trigger_percent': safe_float('pyramiding_trigger', 1.0), 'allow_multiple_per_pair': v.get('allow_multi_pair', tk.BooleanVar()).get() if 'allow_multi_pair' in v else False}
        self.config['daily_drawdown'] = {'enabled': v['dd_enabled'].get(), 'max_loss_percent': safe_float('dd_max_percent', 5), 'max_loss_idr': safe_int('dd_max_idr', 500000), 'reset_time': v['dd_reset_time'].get()}
        self.config['trading_session'] = {'enabled': v['ts_enabled'].get(), 'start_time': v['ts_start'].get(), 'end_time': v['ts_end'].get(), 'timezone': 'Asia/Jakarta', 'action_outside_session': 'pause'}
        self.config['max_holding_time'] = {'enabled': v['mh_enabled'].get(), 'max_hours': safe_int('mh_hours', 24), 'action': 'market_close', 'notification_warning_minutes': safe_int('mh_warning', 60)}
        self.config['backtest'] = {'max_candles': safe_int('bt_max_candles', 5000)}
        self.config['telegram'] = {'enabled': v['tg_enabled'].get(), 'token': v['tg_token'].get(), 'chat_id': v['tg_chat_id'].get(), 'receive_commands': v['tg_receive'].get()}
        self.config['webhook'] = {'enabled': v['wh_enabled'].get(), 'port': safe_int('wh_port', 5000), 'endpoint': '/webhook', 'allowed_symbols': v['wh_symbols'].get()}

        if hasattr(self, 'pair_check_vars'):
            selected = [p for p, var in self.pair_check_vars.items() if var.get()]
            self.config['trading_pairs'] = selected
        else:
            pairs_raw = v['trading_pairs'].get().strip()
            self.config['trading_pairs'] = [p.strip() for p in pairs_raw.split(',') if p.strip()] if pairs_raw else []

        self.save_config()
        self.exchange = Exchange(self.config)
        self.strategy = Strategy(self.config)
        self.risk_manager = RiskManager(self.config)
        self.time_manager = TimeManager(self.config)
        self.adaptive = AdaptiveStrategy(self.config)
        self.telegram = TelegramBot(self.config)
        self.telegram.register_commands()
        self.telegram.set_handlers(profit_fn=self._get_profit_data, positions_fn=self._get_positions_data, stop_fn=self._telegram_stop, resume_fn=self._telegram_resume, get_config_fn=lambda: self.config)
        self.current_mode = self.config.get('trading_mode', 'BUY & SELL')
        self.update_mode_display()
        self.append_log("Settings saved and reloaded!")

    def reset_settings(self):
        v = self.settings_vars
        defaults = {'exchange_name': 'indodax', 'api_key': '', 'api_secret': '', 'entry_tf': 'M5', 'trend_tf': 'H4', 'ema_fast': 50, 'ema_slow': 200, 'rsi_period': 14, 'divergence_ind': 'RSI', 'doji_threshold': 0.001, 'auto_lot_balance': 10000000, 'risk_multiplier': 1, 'atr_period': 14, 'atr_multiplier': 1.5, 'min_rr_ratio': 2.0, 'max_positions': 3, 'pyramiding_trigger': 1.0, 'dd_enabled': True, 'dd_max_percent': 5, 'dd_max_idr': 500000, 'dd_reset_time': '00:00', 'ts_enabled': True, 'ts_start': '08:00', 'ts_end': '22:00', 'mh_enabled': True, 'mh_hours': 24, 'mh_warning': 60, 'bt_max_candles': 5000, 'tg_enabled': False, 'tg_token': '', 'tg_chat_id': '', 'tg_receive': True, 'wh_enabled': False, 'wh_port': 5000, 'wh_symbols': '', 'trading_pairs': ''}
        for key, val in defaults.items():
            if key in v:
                if isinstance(val, bool):
                    v[key].set(val)
                else:
                    v[key].set(str(val))
        self.append_log("Settings reset to defaults (click Save to apply)")

    def refresh_data(self):
        self.append_log("Refreshing data...")
        self.update_balance_display()
        self.scan_pairs()
        self.update_drawdown_display()
        self.update_session_display()
        self.update_adaptive_display()
        self.append_log("Refresh complete")

    def scan_pairs(self):
        try:
            tickers = self.exchange.get_tickers()
            self.trading_pairs = []
            config_pairs = self.config.get('trading_pairs', [])
            for pair in tickers:
                if pair.endswith('_idr') or pair.endswith('IDR'):
                    if not config_pairs or pair in config_pairs:
                        self.trading_pairs.append(pair)
            self.trading_pairs.sort()
            self.append_log(f"Found {len(self.trading_pairs)} trading pairs")
            if hasattr(self, 'chart_pair_menu'):
                self.chart_pair_menu['values'] = self.trading_pairs
        except Exception as e:
            self.append_log(f"Error scanning pairs: {e}")

    def update_balance_display(self):
        try:
            if self.exchange.api_key:
                self.balances = self.exchange.get_balance()
                idr = self.balances.get('idr', 0)
                btc = self.balances.get('btc', 0)
                eth = self.balances.get('eth', 0)
                self.balance_idr_label.config(text=f"IDR: Rp {idr:,.2f}")
                self.balance_coin_label.config(text=f"BTC: {btc:.6f} | ETH: {eth:.6f}")
                self.status_label.config(text="Connected", fg='#00ff00')
                self.api_error_label.config(text="")
        except Exception as e:
            self.status_label.config(text="Disconnected", fg='#ff0000')
            err_msg = str(e)
            if "API Key" in err_msg or "apiKey" in err_msg:
                self.show_api_error("API Key Error: Periksa API Key di Settings.")
            elif "Signature" in err_msg or "sign" in err_msg:
                self.show_api_error("API Key Error: Signature invalid. Periksa API Secret.")
            else:
                self.show_api_error(f"Connection Error: {err_msg[:100]}")

    def update_drawdown_display(self):
        stats = self.risk_manager.get_daily_stats()
        max_loss = self.config['daily_drawdown']['max_loss_idr']
        current_loss = stats['total_loss']
        self.drawdown_label.config(text=f"Rp {current_loss:,.0f} / Rp {max_loss:,.0f}")
        percentage = min((current_loss / max_loss) * 100 if max_loss > 0 else 0, 100)
        self.drawdown_bar['value'] = percentage
        if percentage > 80:
            self.drawdown_label.config(fg='#ff0000')
        elif percentage > 60:
            self.drawdown_label.config(fg='#ffaa00')
        else:
            self.drawdown_label.config(fg='#00ff00')

    def start_bot(self):
        if self.bot_running:
            return
        if not self.exchange.api_key or not self.exchange.api_secret:
            messagebox.showwarning("Warning", "Please set API Key and Secret in Settings tab first.")
            return

        self.btn_start.config(state=tk.DISABLED, text="Testing...")
        self.status_label.config(text="Testing...", fg='#ffaa00')
        self.root.update()

        def do_connect_test():
            try:
                result = self.exchange.test_connection()
                if result.get("overall_status") != "CONNECTED":
                    error_msg = "Connection failed!\n\n"
                    error_msg += f"Public: {result.get('public', {}).get('message', 'Error')}\n"
                    error_msg += f"Private: {result.get('private', {}).get('message', 'Error')}"
                    self.root.after(0, lambda: self._show_connect_fail(error_msg))
                    return
                self.root.after(0, self._proceed_start_bot)
            except Exception as e:
                self.root.after(0, lambda: self._show_connect_fail(str(e)))

        threading.Thread(target=do_connect_test, daemon=True).start()

    def _show_connect_fail(self, msg):
        self.btn_start.config(state=tk.NORMAL, text="START BOT")
        self.status_label.config(text="Disconnected", fg='#ff0000')
        messagebox.showerror("Connection Failed", msg)

    def _proceed_start_bot(self):
        self.bot_running = True
        self.stop_event.clear()
        self.warned_holdings.clear()
        self.btn_start.config(state=tk.DISABLED, text="START BOT")
        self.btn_stop.config(state=tk.NORMAL)
        self.status_label.config(text="Running", fg='#00ff00')
        self.telegram.send_bot_start()

        if self.config.get('webhook', {}).get('enabled', False):
            self.webhook_server.start()

        self.bot_thread = threading.Thread(target=self.trading_loop, daemon=True)
        self.bot_thread.start()
        self.append_log("Bot started")

    def stop_bot(self):
        if not self.bot_running:
            return
        if self.force_close_var.get():
            result = messagebox.askyesno("Force Close All", "PERINGATAN! Anda akan menutup semua posisi yang sedang terbuka.\nTindakan ini TIDAK bisa dibatalkan.\nLanjutkan?")
            if not result:
                return
            self.append_log("Force closing all positions...")
            self.close_all_positions()
        self.bot_running = False
        self.stop_event.set()
        if self.webhook_server:
            self.webhook_server.stop()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.status_label.config(text="Stopped", fg='#ffaa00')
        self.telegram.send_bot_stop()
        self.append_log("Bot stopped")

    def close_all_positions(self):
        open_trades = self.risk_manager.get_open_trades()
        if not open_trades:
            self.append_log("No open positions to close.")
            return

        success_count = 0
        fail_count = 0
        skip_count = 0
        total = len(open_trades)

        self.append_log(f"Force closing {total} positions...")

        for trade in open_trades:
            trade_id = trade[0]
            symbol = trade[1]

            if self.risk_manager.is_trade_closing_or_closed(trade_id):
                skip_count += 1
                continue

            try:
                trade_id, symbol, side, quantity, entry_price = trade[0], trade[1], trade[2], trade[3], trade[4]
                if side == 'BUY':
                    result = self.exchange.market_sell(symbol, quantity)
                else:
                    klines = self.exchange.get_klines(symbol, 'M5', 1)
                    current_price = klines[-1]['close'] if klines else entry_price
                    result = self.exchange.market_buy(symbol, quantity, price=current_price)
                if result:
                    exit_price = float(result.get('price', 0))
                    pnl = self.risk_manager.close_trade(trade_id, exit_price, "force_close")
                    if pnl is None:
                        skip_count += 1
                        self.append_log(f"  [WARNING] Skip: {symbol} already closing/closed")
                        continue
                    self.telegram.send_exit_signal(symbol, entry_price, exit_price, 0, side)
                    self.append_log(f"  Closed: {side} {quantity} {symbol}")
                    success_count += 1
                else:
                    fail_count += 1
                    self.append_log(f"  [ERROR] Failed to close {symbol}: No response from exchange")
            except Exception as e:
                err_str = str(e).lower()
                if "not found" in err_str or "already" in err_str or "closed" in err_str:
                    self.risk_manager.close_trade(trade_id, 0, "force_close")
                    skip_count += 1
                    self.append_log(f"  [WARNING] Skip: {symbol} already closed")
                else:
                    fail_count += 1
                    self.append_log(f"  [ERROR] Failed to close {symbol}: {e}")
                continue

        summary = f"Force Close done. Success: {success_count}, Failed: {fail_count}, Skipped: {skip_count}, Total: {total}"
        self.append_log(summary)
        self.telegram.send_message(f"*KAMSIADI.Inc Bot*\n\n*Force Close Summary*\n{summary}")

    def trading_loop(self):
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self.bot_running and not self.stop_event.is_set():
            try:
                if not self.time_manager.is_within_session():
                    if not self.session_paused:
                        self.session_paused = True
                        _, info = self.time_manager.get_session_status()
                        self.append_log(f"Outside trading session: {info}")
                        self.telegram.send_session_status("PAUSED", info)
                    time.sleep(60)
                    self.root.after(0, self.update_session_display)
                    continue
                else:
                    if self.session_paused:
                        self.session_paused = False
                        _, info = self.time_manager.get_session_status()
                        self.append_log(f"Trading session resumed: {info}")
                        self.telegram.send_session_status("ACTIVE", info)

                self.check_daily_drawdown()
                self.monitor_sl_tp()
                self.check_max_holding_times()
                self.telegram.poll_commands()

                if hasattr(self, 'webhook_server') and self.webhook_server:
                    if self.config.get('webhook', {}).get('enabled', False) and not self.webhook_server.is_alive():
                        self.telegram.send_message("*KAMSIADI.Inc Bot*\n\nWebhook server is DOWN! Restart required.")
                        self.append_log("[ERROR] Webhook server is DOWN!")

                if self.risk_manager.bot_status == "PAUSED":
                    self.append_log("Bot PAUSED due to daily drawdown limit")
                    time.sleep(60)
                    continue

                if self.adaptive.enabled:
                    idr = self.exchange.get_idr_balance() if not self.paper_mode else self.paper_engine.get_balance()
                    result = self.adaptive.get_strategy_for_balance(idr)
                    if result and result.get('changed'):
                        self.adaptive.apply_tier(self.config, result['tier'])
                        self.telegram.send_adaptive_switch(result['old_tier'], result['new_tier'], idr)
                        self.current_mode = self.config.get('trading_mode', 'BUY & SELL')
                        self.root.after(0, self.update_mode_display)
                        self.append_log(f"Adaptive: {result['old_tier']} -> {result['new_tier']}")
                    self.root.after(0, self.update_adaptive_display)

                for pair in self.trading_pairs:
                    if self.stop_event.is_set():
                        break
                    signal = self.check_signal(pair)
                    if signal:
                        self.execute_signal(pair, signal)
                    time.sleep(1)

                consecutive_errors = 0
                time.sleep(5)
            except Exception as e:
                consecutive_errors += 1
                self.append_log(f"Error in trading loop ({consecutive_errors}/{max_consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    self.append_log("[CRITICAL] Too many consecutive errors! Bot auto-stopped.")
                    self.telegram.send_message("*KAMSIADI.Inc Bot*\n\nBot STOPPED: Too many consecutive API errors.")
                    self.stop_bot()
                    return

                time.sleep(30)

    def check_signal(self, pair):
        try:
            tf_entry = self.config['timeframe']['entry']
            tf_trend = self.config['timeframe']['trend']
            wait_close = self.config.get('strategy', {}).get('wait_for_candle_close', False)

            if wait_close:
                klines_ltf = self.exchange.get_klines(pair, tf_entry, 201)
                klines_htf = self.exchange.get_klines(pair, tf_trend, 201)
                if len(klines_ltf) > 1:
                    klines_ltf = klines_ltf[:-1]
                if len(klines_htf) > 1:
                    klines_htf = klines_htf[:-1]
            else:
                klines_ltf = self.exchange.get_klines(pair, tf_entry, 200)
                klines_htf = self.exchange.get_klines(pair, tf_trend, 200)

            if len(klines_ltf) < 50 or len(klines_htf) < 50:
                return None
            signal, trend, divergence = self.strategy.get_entry_signal(klines_htf, klines_ltf)
            if signal is None:
                return None
            mode = self.current_mode
            if mode == "BUY ONLY" and signal != "BUY":
                return None
            if mode == "SELL ONLY" and signal != "SELL":
                return None
            price = klines_ltf[-1]['close']
            return {'pair': pair, 'signal': signal, 'trend': trend, 'divergence': divergence, 'price': price, 'klines': klines_ltf}
        except Exception as e:
            self.append_log(f"Error checking signal for {pair}: {e}")
            return None

    def execute_signal(self, pair, signal_data):
        try:
            if not self.risk_manager.can_open_position():
                return

            pair = signal_data['pair']

            allow_multi = self.config.get('risk_management', {}).get('allow_multiple_per_pair', False)
            if not allow_multi and self.risk_manager.has_open_position_for_pair(pair):
                return

            direction = signal_data['signal']
            price = signal_data['price']
            klines = signal_data['klines']
            idr_balance = self.exchange.get_idr_balance() if not self.paper_mode else self.paper_engine.get_balance()
            lot = self.risk_manager.calculate_lot(idr_balance)
            if lot <= 0:
                return
            sl = self.strategy.calculate_stop_loss(klines, price, direction)
            tp = self.strategy.calculate_take_profit(price, sl, direction)
            self.append_log(f"Signal: {direction} {pair} @ Rp {price:,.2f}")
            self.append_log(f"SL: Rp {sl:,.2f} | TP: Rp {tp:,.2f}")

            if self.paper_mode:
                trade_id, msg = self.paper_engine.execute_order(pair, direction, lot, price)
                if trade_id:
                    conn = __import__('sqlite3').connect(self.paper_engine.db_path)
                    cursor = conn.cursor()
                    cursor.execute('UPDATE paper_trades SET sl_price = ?, tp_price = ? WHERE id = ?', (sl, tp, trade_id))
                    conn.commit()
                    conn.close()
                    self.telegram.send_entry_signal(direction, pair, price, lot)
                    self.append_log(f"Paper Order executed: {direction} {lot} {pair}")
                return

            if direction == 'BUY':
                result = self.exchange.market_buy(pair, lot, price=price)
            else:
                result = self.exchange.market_sell(pair, lot)
            if result:
                trade_id = self.risk_manager.record_trade(pair, direction, lot, price, 'OPEN', sl, tp)
                self.telegram.send_entry_signal(direction, pair, price, lot)
                self.logger.trade(direction, pair, lot, price)
                self.append_log(f"Order executed: {direction} {lot} {pair}")
        except Exception as e:
            self.append_log(f"Error executing signal: {e}")
            self.telegram.send_error(str(e))

    def check_daily_drawdown(self):
        try:
            idr_balance = self.exchange.get_idr_balance()
            initial_equity = self.config['risk_management']['auto_lot_balance'] * 10
            current_equity = idr_balance
            open_trades = self.risk_manager.get_open_trades()
            for trade in open_trades:
                symbol, side, quantity, entry_price = trade[1], trade[2], trade[3], trade[4]
                klines = self.exchange.get_klines(symbol, 'M5', 1)
                if klines:
                    current_price = klines[-1]['close']
                    if side == 'BUY':
                        current_equity += (current_price - entry_price) * quantity
                    else:
                        current_equity += (entry_price - current_price) * quantity
            tz = self.time_manager.tz if self.time_manager else None
            if self.risk_manager.check_daily_drawdown(current_equity, initial_equity, tz):
                self.append_log("DAILY DRAWDOWN LIMIT REACHED!")
                self.close_all_positions()
                self.risk_manager.bot_status = "PAUSED"
                self.telegram.send_drawdown_triggered(self.risk_manager.daily_loss)
                self.stop_bot()
                return
            self.root.after(0, self.update_drawdown_display)
        except Exception as e:
            self.append_log(f"Error checking drawdown: {e}")

    def monitor_sl_tp(self):
        if not hasattr(self, '_last_sl_tp_warn'):
            self._last_sl_tp_warn = 0

        try:
            open_trades = self.risk_manager.get_open_trades()
            for trade in open_trades:
                trade_id = trade[0]
                symbol = trade[1]
                side = trade[2]
                quantity = trade[3]
                entry_price = trade[4]
                sl_price = trade[9] if len(trade) > 9 else 0
                tp_price = trade[10] if len(trade) > 10 else 0

                if sl_price == 0 and tp_price == 0:
                    continue

                if self.risk_manager.is_trade_closing_or_closed(trade_id):
                    continue

                try:
                    klines = self.exchange.get_klines(symbol, 'M5', 1)
                    if not klines:
                        continue
                    current_price = klines[-1]['close']
                except Exception:
                    continue

                exit_reason = ""
                should_close = False

                if side == 'BUY':
                    if sl_price > 0 and current_price <= sl_price:
                        exit_reason = "sl"
                        should_close = True
                    elif tp_price > 0 and current_price >= tp_price:
                        exit_reason = "tp"
                        should_close = True
                else:
                    if sl_price > 0 and current_price >= sl_price:
                        exit_reason = "sl"
                        should_close = True
                    elif tp_price > 0 and current_price <= tp_price:
                        exit_reason = "tp"
                        should_close = True

                if should_close:
                    try:
                        if side == 'BUY':
                            result = self.exchange.market_sell(symbol, quantity)
                        else:
                            result = self.exchange.market_buy(symbol, quantity, price=current_price)

                        exit_price = float(result.get('price', 0)) if result else current_price
                        pnl = self.risk_manager.close_trade(trade_id, exit_price, exit_reason)

                        if pnl is None:
                            self.append_log(f"[WARNING] Skip close: {symbol} already closed/closing")
                            continue

                        msg = f"{'STOP LOSS' if exit_reason == 'sl' else 'TAKE PROFIT'} HIT!"
                        msg += f" {symbol} {side} @ Rp {exit_price:,.2f} | PnL: Rp {pnl:,.2f}"
                        self.append_log(msg)
                        self.telegram.send_exit_signal(symbol, entry_price, exit_price, pnl, side)
                    except Exception as e:
                        err_str = str(e).lower()
                        if "not found" in err_str or "already" in err_str or "closed" in err_str:
                            self.risk_manager.close_trade(trade_id, current_price, exit_reason)
                            continue
                        self.append_log(f"[WARNING] Error closing {symbol} on {exit_reason}: {e}")

        except Exception as e:
            now = time.time()
            if now - self._last_sl_tp_warn > 600:
                self._last_sl_tp_warn = now
                self.append_log(f"[WARNING] SL/TP monitor error: {e}")
                self.telegram.send_message(f"*KAMSIADI.Inc Bot*\n\nWarning: SL/TP monitor error. Bot continues running.")

    def check_max_holding_times(self):
        if not self.config.get('max_holding_time', {}).get('enabled', False):
            return
        open_trades = self.risk_manager.get_open_trades()
        max_hours = self.config['max_holding_time'].get('max_hours', 24)
        warning_mins = self.config['max_holding_time'].get('notification_warning_minutes', 60)
        for trade in open_trades:
            trade_id = trade[0]
            symbol = trade[1]

            if self.risk_manager.is_trade_closing_or_closed(trade_id):
                continue

            side = trade[2]
            quantity = trade[3]
            entry_price = trade[4]
            timestamp = trade[6] if len(trade) > 6 else None
            if not timestamp:
                continue
            expired, holding_hours = self.time_manager.check_holding_time(timestamp, max_hours)
            if expired:
                try:
                    if side == 'BUY':
                        result = self.exchange.market_sell(symbol, quantity)
                    else:
                        klines = self.exchange.get_klines(symbol, 'M5', 1)
                        current_price = klines[-1]['close'] if klines else entry_price
                        result = self.exchange.market_buy(symbol, quantity, price=current_price)
                    exit_price = float(result.get('price', 0)) if result else 0
                    pnl = self.risk_manager.close_trade(trade_id, exit_price, "timeout")
                    if pnl is None:
                        self.append_log(f"[WARNING] Skip max hold close: {symbol} already closing/closed")
                        continue
                    hold_str = self.time_manager.format_holding_time(timestamp, max_hours)
                    self.telegram.send_max_hold_closed(symbol, hold_str, pnl)
                    self.telegram.send_exit_signal(symbol, entry_price, exit_price, pnl, side)
                    self.append_log(f"MAX HOLD: Closed {symbol} after {hold_str} | PnL: Rp {pnl:,.2f}")
                except Exception as e:
                    err_str = str(e).lower()
                    if "not found" in err_str or "already" in err_str or "closed" in err_str:
                        self.risk_manager.close_trade(trade_id, 0, "timeout")
                    else:
                        self.append_log(f"[WARNING] Error closing expired {symbol}: {e}")
            elif self.time_manager.should_warn_holding(timestamp, max_hours):
                if trade_id not in self.warned_holdings:
                    self.warned_holdings.add(trade_id)
                    remaining = int((max_hours - holding_hours) * 60)
                    self.telegram.send_max_hold_warning(symbol, remaining)
                    self.append_log(f"Warning: {symbol} expires in {remaining} minutes")

    def load_chart(self):
        pair = self.chart_pair_var.get()
        tf = self.chart_tf_var.get()
        if not pair:
            self.append_log("Select a pair first")
            return
        try:
            self.chart_text.delete('1.0', tk.END)
            self.chart_text.insert(tk.END, f"  Loading {pair} {tf}...\n")
            self.root.update()
            klines = self.exchange.get_klines(pair, tf, 100)
            if not klines:
                self.chart_text.delete('1.0', tk.END)
                self.chart_text.insert(tk.END, f"  No data for {pair} {tf}.\n\n")
                self.chart_text.insert(tk.END, "  Possible reasons:\n")
                self.chart_text.insert(tk.END, "  - API Key not set or invalid (check Settings)\n")
                self.chart_text.insert(tk.END, "  - Pair does not exist on this exchange\n")
                self.chart_text.insert(tk.END, "  - Network connection issue\n")
                return
            closes = [k['close'] for k in klines]
            import numpy as np
            import pandas as pd
            ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().values if len(closes) > 50 else np.array(closes)
            ema200 = pd.Series(closes).ewm(span=200, adjust=False).mean().values if len(closes) > 200 else np.array(closes)

            self.chart_text.delete('1.0', tk.END)

            title = f"  {pair.upper()} - {tf} - {len(klines)} candles"
            self.chart_text.insert(tk.END, title + "\n")
            self.chart_text.insert(tk.END, "  " + "=" * 85 + "\n\n")

            display_klines = klines[-40:]
            start_idx = len(klines) - len(display_klines)

            for i, k in enumerate(display_klines):
                idx = start_idx + i
                ts = datetime.fromtimestamp(k['open_time'] / 1000).strftime('%m-%d %H:%M')
                o, h, l, c = k['open'], k['high'], k['low'], k['close']
                vol = k.get('volume', 0)
                e50 = f"{ema50[idx]:>10,.0f}" if idx < len(ema50) else f"{'N/A':>10}"
                e200 = f"{ema200[idx]:>10,.0f}" if idx < len(ema200) else f"{'N/A':>10}"

                change = ((c - o) / o * 100) if o > 0 else 0
                color_marker = "+" if c >= o else "-"

                line = f"  {ts}  O:{o:>10,.0f} H:{h:>10,.0f} L:{l:>10,.0f} C:{c:>10,.0f} | EMA50:{e50} EMA200:{e200} | {color_marker}{abs(change):.1f}%\n"
                self.chart_text.insert(tk.END, line)

            last = klines[-1]
            first = klines[0]
            period_change = ((last['close'] - first['open']) / first['open'] * 100) if first['open'] > 0 else 0

            self.chart_text.insert(tk.END, "\n  " + "=" * 85 + "\n")
            self.chart_text.insert(tk.END, f"  Last: {last['close']:,.0f} | Period: {'+' if period_change >= 0 else ''}{period_change:.2f}% | Vol: {last.get('volume', 0):,.2f}\n")

            if len(ema50) > len(klines) - 1 and len(ema200) > len(klines) - 1:
                last_ema50 = ema50[-1]
                last_ema200 = ema200[-1]
                if last_ema50 > last_ema200:
                    self.chart_text.insert(tk.END, "  Trend: UPTREND (EMA50 > EMA200)\n")
                else:
                    self.chart_text.insert(tk.END, "  Trend: DOWNTREND (EMA50 < EMA200)\n")

        except Exception as e:
            self.chart_text.delete('1.0', tk.END)
            self.chart_text.insert(tk.END, f"  Error loading chart: {e}\n\n")
            self.chart_text.insert(tk.END, "  Make sure API Key is configured in Settings tab.\n")

    def refresh_chart(self):
        self.load_chart()

    def _get_profit_data(self):
        stats = self.risk_manager.get_daily_stats()
        return {'realized': -stats.get('realized_loss', 0), 'floating': -stats.get('floating_loss', 0), 'total': -stats.get('total_loss', 0)}

    def _get_positions_data(self):
        open_trades = self.risk_manager.get_open_trades()
        positions = []
        for trade in open_trades:
            symbol, side, quantity, entry_price = trade[1], trade[2], trade[3], trade[4]
            timestamp = trade[6] if len(trade) > 6 else None
            max_hours = self.config.get('max_holding_time', {}).get('max_hours', 24)
            _, holding_hours = self.time_manager.check_holding_time(timestamp, max_hours) if timestamp else (False, 0)
            remaining = max_hours - holding_hours
            hours = int(max(0, remaining))
            mins = int((remaining - hours) * 60) if remaining > 0 else 0
            positions.append({'symbol': symbol, 'entry': entry_price, 'pnl_pct': 0, 'time_left': f"{hours}h {mins}m"})
        return positions

    def _telegram_stop(self):
        self.root.after(0, self.stop_bot)

    def _telegram_resume(self):
        self.root.after(0, self.start_bot)

    def on_close(self):
        if self.bot_running:
            if messagebox.askokcancel("Quit", "Bot is running. Quit anyway?"):
                self.bot_running = False
                self.stop_event.set()
                self.root.destroy()
        else:
            self.root.destroy()


def print_banner():
    print("\n" + "=" * 45)
    print("|  PRIVATE TRADING BOT KAMSIADI.Inc      |")
    print("|  Version 1.0.0                         |")
    print("|  Status: [READY]                       |")
    print("=" * 45 + "\n")


def run_backtest(config):
    print("\nRunning backtest...")
    backtester = Backtester(config)
    exchange = Exchange(config)
    max_candles = config.get('backtest', {}).get('max_candles', 5000)
    print(f"Max candles: {max_candles}")
    print("Fetching historical data...")
    try:
        pairs = config.get('trading_pairs', ['btc_idr'])
        if not pairs:
            pairs = ['btc_idr']
        pair = pairs[0]
        klines_htf = exchange.get_klines(pair, config['timeframe']['trend'], max_candles)
        klines_ltf = exchange.get_klines(pair, config['timeframe']['entry'], max_candles)
        if not klines_htf or not klines_ltf:
            print("Error: Could not fetch historical data")
            return
        results = backtester.run_backtest(klines_htf, klines_ltf)
        backtester.display_results()
    except Exception as e:
        print(f"Backtest error: {e}")


def main():
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    error_log = os.path.join(app_dir, 'error.log')

    try:
        print_banner()
    except Exception:
        pass

    try:
        with open(error_log, 'w') as f:
            f.write(f"Starting bot from: {app_dir}\n")
            f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                f.write(f"MEIPASS: {sys._MEIPASS}\n")

        if len(sys.argv) > 1 and sys.argv[1] == '--backtest':
            config_path = os.path.join(app_dir, 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                run_backtest(config)
            else:
                print("config.json not found")
            input("\nPress Enter to exit...")
            return

        with open(error_log, 'a') as f:
            f.write("Creating Tk root...\n")
        root = tk.Tk()
        with open(error_log, 'a') as f:
            f.write("Creating TradingBotGUI...\n")
        app = TradingBotGUI(root)
        with open(error_log, 'a') as f:
            f.write("Starting mainloop...\n")
        root.mainloop()
        with open(error_log, 'a') as f:
            f.write("Mainloop ended.\n")
    except Exception as e:
        import traceback
        with open(error_log, 'a') as f:
            f.write(f"\nFATAL ERROR: {e}\n")
            f.write(traceback.format_exc())
        try:
            input("\nPress Enter to exit...")
        except Exception:
            pass


if __name__ == "__main__":
    main()
