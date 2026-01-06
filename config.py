"""
Configuration for Relay Guard Bot - Community Moderator
"""
import os

# Bot settings
BOT_TOKEN = os.environ.get("RELAY_GUARD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin IDs (can override bot decisions)
ADMIN_IDS = [6394311885]  # Your Telegram ID

# TEST MODE - only warn, never ban/mute
TEST_MODE = False

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

# Captcha settings
CAPTCHA_TIMEOUT_SECONDS = 120  # 2 minutes to solve
CAPTCHA_KICK_ON_FAIL = True  # Kick if not solved

# Rep settings
REP_COOLDOWN_SECONDS = 3600  # 1 hour between giving rep to same user
REP_POINTS_MANUAL = 2  # Points for manual +rep

# Paths
from pathlib import Path
DATA_DIR = Path(__file__).parent / "data"
VIOLATIONS_FILE = DATA_DIR / "violations.json"
REPORTS_FILE = DATA_DIR / "reports.json"
CAPTCHA_FILE = DATA_DIR / "pending_captcha.json"
REP_COOLDOWN_FILE = DATA_DIR / "rep_cooldowns.json"
