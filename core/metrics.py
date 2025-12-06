import json
import os
import logging
from datetime import datetime
from typing import Dict, Any
from collections import defaultdict

from prometheus_client import Gauge, Counter, Histogram

# Global variables
user_states: Dict[int, Dict[str, Any]] = {}
user_stats: Dict[int, Dict[str, int]] = defaultdict(lambda: {"texts": 0, "errors": 0})
bot_stats = {"total_texts": 0, "total_users": 0, "start_time": datetime.now().isoformat()}

# Prometheus metrics
total_users_gauge = Gauge('telegram_bot_total_users', 'Total number of users')
total_texts_gauge = Gauge('telegram_bot_total_texts', 'Total number of texts processed')
total_errors_gauge = Gauge('telegram_bot_total_errors', 'Total number of errors')

# Counters
command_starts = Counter('telegram_bot_command_starts_total', 'Total /start commands')
messages_received = Counter('telegram_bot_messages_received_total', 'Total messages received from users')
bot_errors_sent = Counter('telegram_bot_bot_errors_sent_total', 'Total error messages sent by bot')

# Histograms
file_processing_time = Histogram('telegram_bot_file_processing_seconds', 'Time spent processing files')

# Counters for successful operations
successful_operations = Counter('telegram_bot_successful_operations_total', 'Total successful operations')

# Crypto monitoring metrics
crypto_wallets_total = Gauge('telegram_bot_crypto_wallets_total', 'Total number of crypto wallets being monitored')
crypto_balance_checks = Counter('telegram_bot_crypto_balance_checks_total', 'Total crypto balance checks')
crypto_transaction_checks = Counter('telegram_bot_crypto_transaction_checks_total', 'Total crypto transaction checks')
crypto_api_errors = Counter('telegram_bot_crypto_api_errors_total', 'Total crypto API errors')
crypto_notifications_sent = Counter('telegram_bot_crypto_notifications_sent_total', 'Total crypto transaction notifications sent')

# Text processing availability
try:
    from processors import process_clean, process_dedup, process_smart_clean
    TEXT_PROCESSING_AVAILABLE = True
except ImportError:
    TEXT_PROCESSING_AVAILABLE = False
    print("⚠️ Processor modules not found. Text file processing is unavailable.")

# Placeholder for bot and logger (will be set in main.py)
bot = None
logger = None


def update_metrics():
    """Update Prometheus metrics"""
    total_users = len(user_stats)
    total_texts = sum(stats.get('texts', 0) for stats in user_stats.values())
    total_errors = sum(stats.get('errors', 0) for stats in user_stats.values())
    total_users_gauge.set(total_users)
    total_texts_gauge.set(total_texts)
    total_errors_gauge.set(total_errors)


def load_stats():
    """Load statistics from file"""
    from .config import Config

    try:
        if os.path.exists(Config.STATS_FILE):
            with open(Config.STATS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                global user_stats, bot_stats
                user_stats = defaultdict(lambda: {"texts": 0, "errors": 0}, data.get("user_stats", {}))
                bot_stats = data.get("bot_stats", bot_stats)
        update_metrics()
    except Exception as e:
        if logger:
            logger.error(f"Failed to load statistics: {e}")
        else:
            print(f"Failed to load statistics: {e}")


def save_stats():
    """Save statistics to file"""
    from .config import Config

    try:
        with open(Config.STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "user_stats": dict(user_stats),
                "bot_stats": bot_stats
            }, f, ensure_ascii=False, indent=2)
        update_metrics()
    except Exception as e:
        if logger:
            logger.error(f"Failed to save statistics: {e}")
        else:
            print(f"Failed to save statistics: {e}")


def init_bot_components(bot_instance, logger_instance):
    """Initialize bot and logger references"""
    global bot, logger
    bot = bot_instance
    logger = logger_instance
