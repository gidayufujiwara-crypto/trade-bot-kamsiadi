import json
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify


class WebhookServer:
    def __init__(self, config, execute_callback=None, logger=None):
        self.config = config.get('webhook', {})
        self.enabled = self.config.get('enabled', False)
        self.port = self.config.get('port', 5000)
        self.endpoint = self.config.get('endpoint', '/webhook')
        self.allowed_symbols = [
            s.strip().upper() for s in self.config.get('allowed_symbols', '').split(',') if s.strip()
        ]
        self.execute_callback = execute_callback
        self.logger = logger
        self.app = Flask(__name__)
        self.server_thread = None
        self.running = False
        self.last_health = None
        self._setup_routes()

    def _log(self, msg):
        if self.logger:
            self.logger.info(f"[Webhook] {msg}")

    def _log_error(self, msg):
        if self.logger:
            self.logger.error(f"[Webhook] {msg}")

    def _setup_routes(self):
        @self.app.errorhandler(Exception)
        def handle_exception(e):
            self._log_error(f"Unhandled error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

        @self.app.route(self.endpoint, methods=['POST'])
        def webhook():
            try:
                data = request.get_json(force=True)
                signal = data.get('signal', '').upper()
                symbol = data.get('symbol', '').upper()
                price = float(data.get('price', 0))

                self._log(f"Received: {signal} {symbol} @ {price}")

                if signal not in ('BUY', 'SELL'):
                    return jsonify({"error": "Invalid signal"}), 400

                if self.allowed_symbols and symbol not in self.allowed_symbols:
                    return jsonify({"error": f"Symbol {symbol} not allowed"}), 403

                if self.execute_callback:
                    self.execute_callback({
                        'signal': signal,
                        'symbol': symbol,
                        'price': price,
                        'source': 'webhook'
                    })

                self.last_health = datetime.now().isoformat()
                return jsonify({"status": "ok", "signal": signal, "symbol": symbol, "timestamp": self.last_health})
            except Exception as e:
                self._log_error(f"Webhook error: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                "status": "alive",
                "timestamp": datetime.now().isoformat(),
                "last_signal": self.last_health,
                "port": self.port,
                "allowed_symbols": self.allowed_symbols
            })

    def start(self):
        if not self.enabled:
            return
        if self.running:
            return
        self.running = True
        self.server_thread = threading.Thread(target=self._run, daemon=True)
        self.server_thread.start()
        self._log(f"Webhook server started on port {self.port}")

    def _run(self):
        retry_count = 0
        max_retries = 5
        while self.running and retry_count < max_retries:
            try:
                self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False, threaded=True)
                break
            except Exception as e:
                retry_count += 1
                self._log_error(f"Server crash (attempt {retry_count}/{max_retries}): {e}")
                if retry_count < max_retries:
                    time.sleep(5)
        self.running = False
        self._log_error("Webhook server stopped")

    def is_alive(self):
        if not self.enabled:
            return True
        if not self.running:
            return False
        if self.server_thread and not self.server_thread.is_alive():
            return False
        return True

    def stop(self):
        self.running = False
        self._log("Webhook server stop requested")
