import time
import hmac
import hashlib
import json
import requests
from urllib.parse import urlencode


class Exchange:
    def __init__(self, config):
        self.config = config
        self.name = config['exchange']['name'].lower()
        self.api_key = config['exchange']['api_key']
        self.api_secret = config['exchange']['api_secret']
        self.base_url = self._get_base_url()
        self.session = requests.Session()

    def _get_base_url(self):
        if self.name == 'indodax':
            return 'https://indodax.com'
        elif self.name == 'tokocrypto':
            return 'https://api.tokocrypto.com'
        raise ValueError(f"Exchange {self.name} not supported")

    def _generate_signature(self, params):
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        return signature

    def _private_request(self, method_name, params=None):
        if not self.api_key or not self.api_secret:
            raise ValueError("API Key and Secret required")

        timestamp = int(time.time() * 1000)
        if params is None:
            params = {}
        params['timestamp'] = timestamp
        params['apiKey'] = self.api_key

        if self.name == 'indodax':
            params['method'] = method_name
            params['sign'] = self._generate_signature(params)
            url = f"{self.base_url}/tapi"
            response = self.session.post(url, data=params)
        elif self.name == 'tokocrypto':
            params['signature'] = self._generate_signature(params)
            url = f"{self.base_url}{method_name}"
            headers = {'X-MBX-APIKEY': self.api_key}
            response = self.session.post(url, data=params, headers=headers)

        if response.status_code != 200:
            raise Exception(f"API Error: {response.text}")

        return response.json()

    def _public_request(self, endpoint, params=None):
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, params=params)
        if response.status_code != 200:
            raise Exception(f"API Error: {response.text}")
        return response.json()

    def get_tickers(self):
        if self.name == 'indodax':
            data = self._public_request('/api/tickers')
            return data.get('tickers', data)
        elif self.name == 'tokocrypto':
            data = self._public_request('/api/v3/ticker/24hr')
            return {item['symbol']: item for item in data}

    def get_klines(self, symbol, interval, limit=200):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            data = self._private_request('tradeHistory', {
                'pair': pair,
                'start': int(time.time()) - (limit * self._get_interval_seconds(interval)),
                'end': int(time.time())
            })
            return self._format_klines_indodax(data, interval)
        elif self.name == 'tokocrypto':
            data = self._public_request('/api/v3/klines', {
                'symbol': symbol.upper().replace('/', ''),
                'interval': interval,
                'limit': limit
            })
            return self._format_klines_tokocrypto(data)

    def _get_interval_seconds(self, interval):
        intervals = {
            'M1': 60, 'M5': 300, 'M15': 900, 'M30': 1800,
            'H1': 3600, 'H4': 14400, 'D1': 86400
        }
        return intervals.get(interval, 300)

    def _format_klines_indodax(self, data, interval):
        if 'data' not in data:
            return []

        klines = []
        trades = data['data']
        interval_ms = self._get_interval_seconds(interval) * 1000

        current_candle = None
        for trade in trades:
            timestamp = trade['date'] * 1000
            price = float(trade['price'])

            if current_candle is None or timestamp >= current_candle['open_time'] + interval_ms:
                if current_candle:
                    klines.append(current_candle)
                current_candle = {
                    'open_time': timestamp,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': float(trade.get('amount', 0))
                }
            else:
                current_candle['high'] = max(current_candle['high'], price)
                current_candle['low'] = min(current_candle['low'], price)
                current_candle['close'] = price
                current_candle['volume'] += float(trade.get('amount', 0))

        if current_candle:
            klines.append(current_candle)

        return klines[-200:]

    def _format_klines_tokocrypto(self, data):
        klines = []
        for item in data:
            klines.append({
                'open_time': item[0],
                'open': float(item[1]),
                'high': float(item[2]),
                'low': float(item[3]),
                'close': float(item[4]),
                'volume': float(item[5])
            })
        return klines

    def get_balance(self):
        if self.name == 'indodax':
            data = self._private_request('getBalance')
            balances = {}
            if data.get('return'):
                for item in data['return'].get('balance', []):
                    if float(item['balance']) > 0:
                        balances[item['currency'].lower()] = float(item['balance'])
            return balances
        elif self.name == 'tokocrypto':
            data = self._private_request('/api/v3/account')
            balances = {}
            for item in data.get('balances', []):
                free = float(item['free'])
                if free > 0:
                    balances[item['asset'].lower()] = free
            return balances

    def get_idr_balance(self):
        balances = self.get_balance()
        return balances.get('idr', 0)

    def market_buy(self, symbol, quantity, price=None):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            idr_amount = quantity * price if price else quantity
            return self._private_request('trade', {
                'pair': pair,
                'type': 'buy',
                'idr': int(idr_amount)
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'side': 'BUY',
                'type': 'MARKET',
                'quantity': quantity
            })

    def market_sell(self, symbol, quantity):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            return self._private_request('trade', {
                'pair': pair,
                'type': 'sell',
                'coin': quantity
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': quantity
            })

    def limit_buy(self, symbol, quantity, price):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            return self._private_request('trade', {
                'pair': pair,
                'type': 'buy',
                'idr': int(quantity),
                'price': int(price)
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'side': 'BUY',
                'type': 'LIMIT',
                'quantity': quantity,
                'price': price,
                'timeInForce': 'GTC'
            })

    def limit_sell(self, symbol, quantity, price):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            return self._private_request('trade', {
                'pair': pair,
                'type': 'sell',
                'coin': quantity,
                'price': price
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'side': 'SELL',
                'type': 'LIMIT',
                'quantity': quantity,
                'price': price,
                'timeInForce': 'GTC'
            })

    def get_open_orders(self, symbol=None):
        if self.name == 'indodax':
            params = {}
            if symbol:
                params['pair'] = symbol.upper().replace('_IDR', '')
            return self._private_request('openOrders', params)
        elif self.name == 'tokocrypto':
            params = {}
            if symbol:
                params['symbol'] = symbol.upper().replace('/', '')
            return self._private_request('/api/v3/openOrders', params)

    def cancel_order(self, order_id, symbol):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            return self._private_request('cancelOrder', {
                'order_id': order_id,
                'pair': pair
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'orderId': order_id
            })

    def get_order_status(self, order_id, symbol):
        if self.name == 'indodax':
            pair = symbol.upper().replace('_IDR', '')
            return self._private_request('orderStatus', {
                'order_id': order_id,
                'pair': pair
            })
        elif self.name == 'tokocrypto':
            return self._private_request('/api/v3/order', {
                'symbol': symbol.upper().replace('/', ''),
                'orderId': order_id
            })

    def test_connection(self):
        result = {
            "success": False,
            "public": {"status": "error", "message": ""},
            "private": {"status": "error", "message": ""},
            "trade_permission": {"status": "error", "message": ""},
            "overall_status": "DISCONNECTED"
        }

        try:
            if self.name == 'indodax':
                self._public_request('/api/tickers')
            elif self.name == 'tokocrypto':
                self._public_request('/api/v3/ping')
            result["public"] = {"status": "ok", "message": "Public API connected"}
        except Exception as e:
            result["public"] = {"status": "error", "message": str(e)[:100]}
            return result

        if not self.api_key or not self.api_secret:
            result["overall_status"] = "PARTIAL"
            result["trade_permission"] = {"status": "skip", "message": "No API key configured"}
            return result

        try:
            self.get_balance()
            result["private"] = {"status": "ok", "message": "Private API connected"}
        except Exception as e:
            err = str(e).lower()
            if "permission" in err or "invalid" in err or "key" in err:
                result["private"] = {"status": "error", "message": f"API Key error: {str(e)[:80]}"}
            else:
                result["private"] = {"status": "error", "message": str(e)[:100]}
            result["overall_status"] = "DISCONNECTED"
            return result

        result["trade_permission"] = {"status": "ok", "message": "Trade permission verified"}
        result["success"] = True
        result["overall_status"] = "CONNECTED"
        return result
