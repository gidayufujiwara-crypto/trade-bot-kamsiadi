from datetime import datetime, time as dtime
import pytz


class TimeManager:
    def __init__(self, config):
        self.session_config = config.get('trading_session', {})
        self.holding_config = config.get('max_holding_time', {})
        self.tz_name = self.session_config.get('timezone', 'Asia/Jakarta')
        try:
            self.tz = pytz.timezone(self.tz_name)
        except Exception:
            self.tz = pytz.utc

    def get_local_time(self):
        return datetime.now(self.tz)

    def is_within_session(self):
        if not self.session_config.get('enabled', False):
            return True
        now = self.get_local_time().time()
        start = self._parse_time(self.session_config.get('start_time', '08:00'))
        end = self._parse_time(self.session_config.get('end_time', '22:00'))
        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    def get_session_status(self):
        if not self.session_config.get('enabled', False):
            return "DISABLED", ""
        if self.is_within_session():
            start = self.session_config.get('start_time', '08:00')
            end = self.session_config.get('end_time', '22:00')
            return "ACTIVE", f"{start}-{end} WIB"
        else:
            start = self.session_config.get('start_time', '08:00')
            end = self.session_config.get('end_time', '22:00')
            return "PAUSED", f"Diluar jam {start}-{end} WIB"

    def get_session_remaining_minutes(self):
        if not self.session_config.get('enabled', False):
            return 1440
        now = self.get_local_time()
        end = self._parse_time(self.session_config.get('end_time', '22:00'))
        end_dt = now.replace(hour=end.hour, minute=end.minute, second=0)
        if now > end_dt:
            return 0
        delta = end_dt - now
        return int(delta.total_seconds() / 60)

    def check_holding_time(self, entry_timestamp, max_hours=None):
        if not self.holding_config.get('enabled', False):
            return False, 0
        if max_hours is None:
            max_hours = self.holding_config.get('max_hours', 24)
        now = self.get_local_time()
        entry_dt = self._to_aware_datetime(entry_timestamp)
        holding = now - entry_dt
        holding_hours = holding.total_seconds() / 3600
        return holding_hours >= max_hours, holding_hours

    def get_warning_minutes(self):
        return self.holding_config.get('notification_warning_minutes', 60)

    def should_warn_holding(self, entry_timestamp, max_hours=None):
        if not self.holding_config.get('enabled', False):
            return False
        if max_hours is None:
            max_hours = self.holding_config.get('max_hours', 24)
        warning_mins = self.get_warning_minutes()
        now = self.get_local_time()
        entry_dt = self._to_aware_datetime(entry_timestamp)
        holding = now - entry_dt
        remaining_hours = max_hours - (holding.total_seconds() / 3600)
        return 0 < remaining_hours <= (warning_mins / 60)

    def format_holding_time(self, entry_timestamp, max_hours=None):
        _, holding_hours = self.check_holding_time(entry_timestamp, max_hours)
        hours = int(holding_hours)
        mins = int((holding_hours - hours) * 60)
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def get_holding_color(self, entry_timestamp, max_hours=None):
        if not max_hours:
            max_hours = self.holding_config.get('max_hours', 24)
        _, holding_hours = self.check_holding_time(entry_timestamp, max_hours)
        remaining = max_hours - holding_hours
        pct = (remaining / max_hours) * 100 if max_hours > 0 else 100
        if pct > 50:
            return "#00ff00"
        elif pct > 25:
            return "#ffaa00"
        else:
            return "#ff0000"

    def _parse_time(self, time_str):
        parts = time_str.split(':')
        return dtime(int(parts[0]), int(parts[1]))

    def _to_aware_datetime(self, ts):
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                dt = datetime.now()
        elif isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, self.tz)
        else:
            dt = ts if ts else datetime.now()
        if dt.tzinfo is None:
            dt = self.tz.localize(dt)
        return dt
