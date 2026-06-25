class AdaptiveStrategy:
    def __init__(self, config):
        self.config = config.get('adaptive_strategy', {})
        self.enabled = self.config.get('enabled', False)
        self.tiers = self.config.get('balance_tiers', [])
        self.current_tier_index = None

    def get_strategy_for_balance(self, balance):
        if not self.enabled or not self.tiers:
            return None
        for i, tier in enumerate(self.tiers):
            if balance <= tier['max_balance']:
                if self.current_tier_index != i:
                    old_desc = self.tiers[self.current_tier_index]['description'] if self.current_tier_index is not None else "Default"
                    self.current_tier_index = i
                    return {
                        'changed': True,
                        'old_tier': old_desc,
                        'new_tier': tier['description'],
                        'tier': tier
                    }
                return {'changed': False, 'tier': tier}
        last = self.tiers[-1]
        if self.current_tier_index != len(self.tiers) - 1:
            old_desc = self.tiers[self.current_tier_index]['description'] if self.current_tier_index is not None else "Default"
            self.current_tier_index = len(self.tiers) - 1
            return {
                'changed': True,
                'old_tier': old_desc,
                'new_tier': last['description'],
                'tier': last
            }
        return {'changed': False, 'tier': last}

    def apply_tier(self, config, tier):
        if not tier:
            return
        config['trading_mode'] = tier.get('trading_mode', config.get('trading_mode', 'BUY & SELL'))
        config['risk_management']['risk_multiplier'] = tier.get('risk_percent', 1)
        config['risk_management']['max_positions'] = tier.get('max_positions', 3)
        config['risk_management']['min_rr_ratio'] = tier.get('rr_ratio', 2.0)
        config['max_holding_time']['max_hours'] = tier.get('max_holding_hours', 24)
        config['trading_session']['start_time'] = tier.get('trading_session_start', '08:00')
        config['trading_session']['end_time'] = tier.get('trading_session_end', '22:00')

    def get_current_tier(self):
        if self.current_tier_index is not None and self.current_tier_index < len(self.tiers):
            return self.tiers[self.current_tier_index]
        return None

    def get_tier_info(self, balance):
        current = self.get_current_tier()
        if not current:
            return {"name": "Default", "color": "#666666", "progress": 0}
        idx = self.current_tier_index or 0
        if idx < len(self.tiers) - 1:
            next_tier = self.tiers[idx + 1]
            progress = (balance / next_tier['max_balance']) * 100
        else:
            progress = 100
        colors = ["#00aa00", "#ffaa00", "#ff0000"]
        return {
            "name": current.get('description', 'Unknown'),
            "color": colors[min(idx, len(colors) - 1)],
            "progress": min(progress, 100)
        }
