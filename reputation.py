"""
Reputation system for Relay community
+rep for defenders, -rep for violators
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

from config import DATA_DIR

REPUTATION_FILE = DATA_DIR / "reputation.json"

# Rep points
REP_DEFEND_RELAY = 5       # Defended Relay from hater
REP_HELPFUL_ANSWER = 3     # Helped someone
REP_BUG_REPORT = 2         # Reported a bug
REP_POSITIVE_FEEDBACK = 1  # Said something nice about Relay

REP_VIOLATION_WARN = -5    # Got warned
REP_VIOLATION_MUTE = -15   # Got muted
REP_VIOLATION_BAN = -50    # Got banned
REP_SPAM = -20             # Spam


@dataclass
class RepEvent:
    """Single reputation event"""
    event_type: str
    points: int
    reason: str
    timestamp: str


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_reputation() -> dict:
    _ensure_data_dir()
    if REPUTATION_FILE.exists():
        with open(REPUTATION_FILE, "r") as f:
            return json.load(f)
    return {"users": {}}


def _save_reputation(data: dict):
    _ensure_data_dir()
    with open(REPUTATION_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_rep(user_id: int, username: str, points: int, reason: str, event_type: str) -> int:
    """
    Add reputation points to user.
    Returns new total rep.
    """
    data = _load_reputation()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        data["users"][user_id_str] = {
            "username": username,
            "total_rep": 0,
            "history": [],
            "badges": []
        }
    
    user = data["users"][user_id_str]
    user["username"] = username
    user["total_rep"] += points
    
    event = RepEvent(
        event_type=event_type,
        points=points,
        reason=reason,
        timestamp=datetime.now().isoformat()
    )
    user["history"].append(asdict(event))
    
    # Keep only last 50 events
    user["history"] = user["history"][-50:]
    
    # Check for badges
    _check_badges(user)
    
    _save_reputation(data)
    
    return user["total_rep"]


def _check_badges(user: dict):
    """Award badges based on rep and activity"""
    badges = user.get("badges", [])
    total = user["total_rep"]
    history = user.get("history", [])
    
    # Count defense events
    defense_count = sum(1 for e in history if e.get("event_type") == "defend")
    
    # Badge: Defender
    if defense_count >= 3 and "🛡️ Defender" not in badges:
        badges.append("🛡️ Defender")
    
    # Badge: Champion
    if defense_count >= 10 and "⚔️ Champion" not in badges:
        badges.append("⚔️ Champion")
    
    # Badge: Trusted
    if total >= 50 and "⭐ Trusted" not in badges:
        badges.append("⭐ Trusted")
    
    # Badge: Legend
    if total >= 100 and "👑 Legend" not in badges:
        badges.append("👑 Legend")
    
    # Badge: Helper
    help_count = sum(1 for e in history if e.get("event_type") == "helpful")
    if help_count >= 5 and "💡 Helper" not in badges:
        badges.append("💡 Helper")
    
    user["badges"] = badges


def get_rep(user_id: int) -> dict:
    """Get user reputation info"""
    data = _load_reputation()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        return {
            "total_rep": 0,
            "badges": [],
            "rank": "Newcomer"
        }
    
    user = data["users"][user_id_str]
    total = user.get("total_rep", 0)
    
    # Determine rank
    if total < 0:
        rank = "⚠️ Suspicious"
    elif total < 10:
        rank = "Newcomer"
    elif total < 30:
        rank = "Member"
    elif total < 50:
        rank = "Regular"
    elif total < 100:
        rank = "Trusted"
    else:
        rank = "Legend"
    
    return {
        "total_rep": total,
        "badges": user.get("badges", []),
        "rank": rank,
        "history_count": len(user.get("history", []))
    }


def get_leaderboard(limit: int = 10) -> list:
    """Get top users by reputation"""
    data = _load_reputation()
    
    users = [
        {
            "user_id": uid,
            "username": u.get("username", "Unknown"),
            "total_rep": u.get("total_rep", 0),
            "badges": u.get("badges", [])
        }
        for uid, u in data.get("users", {}).items()
    ]
    
    # Sort by rep descending
    users.sort(key=lambda x: x["total_rep"], reverse=True)
    
    return users[:limit]


# Convenience functions
def rep_defend(user_id: int, username: str) -> int:
    """User defended Relay"""
    return add_rep(user_id, username, REP_DEFEND_RELAY, "Defended Relay 🛡️", "defend")


def rep_helpful(user_id: int, username: str) -> int:
    """User was helpful"""
    return add_rep(user_id, username, REP_HELPFUL_ANSWER, "Helpful answer 💡", "helpful")


def rep_bug_report(user_id: int, username: str) -> int:
    """User reported a bug"""
    return add_rep(user_id, username, REP_BUG_REPORT, "Bug report 🐛", "bug_report")


def rep_positive(user_id: int, username: str) -> int:
    """User said something positive"""
    return add_rep(user_id, username, REP_POSITIVE_FEEDBACK, "Positive feedback ❤️", "positive")


def rep_violation(user_id: int, username: str, action: str) -> int:
    """User violated rules"""
    if action == "ban":
        points = REP_VIOLATION_BAN
    elif action == "mute":
        points = REP_VIOLATION_MUTE
    else:
        points = REP_VIOLATION_WARN
    
    return add_rep(user_id, username, points, f"Violation: {action}", "violation")
