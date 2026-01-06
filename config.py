"""
Configuration for Relay Guard Bot - Community Moderator
"""
import os

# Bot settings
BOT_TOKEN = os.environ.get("RELAY_GUARD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin IDs (can override bot decisions)
ADMIN_IDS = [123456789]  # Your Telegram ID

# Group settings
ALLOWED_GROUP_ID = os.environ.get("RELAY_GROUP_ID", "")  # Your group ID

# Moderation settings
WARN_BEFORE_BAN = 3  # Warnings before ban
MUTE_DURATION_MINUTES = 60  # First offense mute duration
BAN_DURATION_DAYS = 7  # Temp ban duration (0 = permanent)

# Spam detection
MAX_MESSAGES_PER_MINUTE = 10
MAX_LINKS_PER_MESSAGE = 2
MIN_ACCOUNT_AGE_DAYS = 1  # New accounts flagged

# Allowed languages
ALLOWED_LANGUAGES = ["en", "ru"]

# Keywords that trigger review (not auto-ban)
SUSPICIOUS_KEYWORDS = [
    "crypto", "invest", "earn money", "click here", "free bitcoin",
    "заработок", "инвестиции", "крипта", "бесплатно"
]

# Auto-ban patterns (regex)
SPAM_PATTERNS = [
    r"t\.me/(?!.*relay)",  # Telegram links except relay
    r"bit\.ly",
    r"tinyurl",
    r"@\w+bot\b",  # Bot mentions
]

# Paths
from pathlib import Path
DATA_DIR = Path(__file__).parent / "data"
VIOLATIONS_FILE = DATA_DIR / "violations.json"
REPORTS_FILE = DATA_DIR / "reports.json"
