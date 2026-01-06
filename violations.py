"""
Violation tracking for Relay Guard Bot
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict

from config import DATA_DIR, VIOLATIONS_FILE, REPORTS_FILE, WARN_BEFORE_BAN


@dataclass
class Violation:
    """Single violation record"""
    user_id: int
    username: str
    violation_type: str
    reason: str
    message_text: str
    action_taken: str
    timestamp: str
    confidence: float


@dataclass 
class Report:
    """User report record"""
    reporter_id: int
    reporter_username: str
    reported_user_id: int
    reported_username: str
    reported_message: str
    reason: str
    status: str  # pending, reviewed, actioned, dismissed
    timestamp: str
    admin_notes: str = ""


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_violations() -> dict:
    _ensure_data_dir()
    if VIOLATIONS_FILE.exists():
        with open(VIOLATIONS_FILE, "r") as f:
            return json.load(f)
    return {"users": {}}


def _save_violations(data: dict):
    _ensure_data_dir()
    with open(VIOLATIONS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_reports() -> dict:
    _ensure_data_dir()
    if REPORTS_FILE.exists():
        with open(REPORTS_FILE, "r") as f:
            return json.load(f)
    return {"reports": []}


def _save_reports(data: dict):
    _ensure_data_dir()
    with open(REPORTS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def record_violation(violation: Violation) -> int:
    """
    Record a violation and return total violation count for user.
    """
    data = _load_violations()
    user_id_str = str(violation.user_id)
    
    if user_id_str not in data["users"]:
        data["users"][user_id_str] = {
            "username": violation.username,
            "violations": [],
            "warnings": 0,
            "mutes": 0,
            "bans": 0
        }
    
    user_data = data["users"][user_id_str]
    user_data["violations"].append(asdict(violation))
    user_data["username"] = violation.username  # Update username
    
    # Update counters
    if violation.action_taken == "warn":
        user_data["warnings"] += 1
    elif violation.action_taken == "mute":
        user_data["mutes"] += 1
    elif violation.action_taken == "ban":
        user_data["bans"] += 1
    
    _save_violations(data)
    
    return len(user_data["violations"])


def get_user_violations(user_id: int) -> dict:
    """Get all violations for a user"""
    data = _load_violations()
    user_id_str = str(user_id)
    
    if user_id_str not in data["users"]:
        return {
            "violations": [],
            "warnings": 0,
            "mutes": 0,
            "bans": 0
        }
    
    return data["users"][user_id_str]


def get_warning_count(user_id: int) -> int:
    """Get warning count for a user"""
    user_data = get_user_violations(user_id)
    return user_data.get("warnings", 0)


def should_escalate(user_id: int) -> tuple[bool, str]:
    """
    Check if user should be escalated to next punishment level.
    Returns (should_escalate, recommended_action)
    """
    user_data = get_user_violations(user_id)
    warnings = user_data.get("warnings", 0)
    mutes = user_data.get("mutes", 0)
    
    if warnings >= WARN_BEFORE_BAN:
        if mutes == 0:
            return True, "mute"
        else:
            return True, "ban"
    
    return False, "warn"


def record_report(report: Report) -> int:
    """Record a user report and return report ID"""
    data = _load_reports()
    
    report_id = len(data["reports"]) + 1
    report_dict = asdict(report)
    report_dict["id"] = report_id
    
    data["reports"].append(report_dict)
    _save_reports(data)
    
    return report_id


def get_pending_reports() -> List[dict]:
    """Get all pending reports"""
    data = _load_reports()
    return [r for r in data["reports"] if r.get("status") == "pending"]


def update_report_status(report_id: int, status: str, admin_notes: str = ""):
    """Update report status"""
    data = _load_reports()
    
    for report in data["reports"]:
        if report.get("id") == report_id:
            report["status"] = status
            report["admin_notes"] = admin_notes
            break
    
    _save_reports(data)


def get_stats() -> dict:
    """Get moderation statistics"""
    violations_data = _load_violations()
    reports_data = _load_reports()
    
    total_violations = sum(
        len(u.get("violations", []))
        for u in violations_data.get("users", {}).values()
    )
    
    total_warnings = sum(
        u.get("warnings", 0)
        for u in violations_data.get("users", {}).values()
    )
    
    total_mutes = sum(
        u.get("mutes", 0)
        for u in violations_data.get("users", {}).values()
    )
    
    total_bans = sum(
        u.get("bans", 0)
        for u in violations_data.get("users", {}).values()
    )
    
    return {
        "total_users_with_violations": len(violations_data.get("users", {})),
        "total_violations": total_violations,
        "total_warnings": total_warnings,
        "total_mutes": total_mutes,
        "total_bans": total_bans,
        "total_reports": len(reports_data.get("reports", [])),
        "pending_reports": len([r for r in reports_data.get("reports", []) if r.get("status") == "pending"])
    }
