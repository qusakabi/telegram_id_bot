import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration"""

    # Core settings
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")

    # File and directory paths
    LOGS_DIR = "logs"
    DATA_DIR = "data"
    STATS_FILE = "data/stats.json"

    # Logging settings
    LOG_LEVEL = "INFO"
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Text processing settings
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB for text files

    @classmethod
    def validate_config(cls) -> bool:
        """Validate configuration"""
        if not cls.BOT_TOKEN:
            print("❌ Error: Bot token not provided (TELEGRAM_BOT_TOKEN or BOT_TOKEN)")
            return False

        # Create required directories
        os.makedirs(cls.LOGS_DIR, exist_ok=True)
        os.makedirs(cls.DATA_DIR, exist_ok=True)

        return True
