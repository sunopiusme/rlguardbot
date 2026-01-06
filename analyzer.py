"""
Message Analyzer for Relay Guard Bot
Smart detection of rule violations
"""
import re
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime, timedelta

from config import (
    SUSPICIOUS_KEYWORDS, SPAM_PATTERNS, 
    MAX_LINKS_PER_MESSAGE, ALLOWED_LANGUAGES
)


@dataclass
class AnalysisResult:
    """Result of message analysis"""
    is_violation: bool
    violation_type: Optional[str]
    confidence: float  # 0.0 - 1.0
    reason: str
    should_delete: bool
    should_warn: bool
    should_mute: bool
    should_ban: bool


class MessageAnalyzer:
    """Analyzes messages for rule violations"""
    
    # Relay-related keywords (on-topic indicators)
    RELAY_KEYWORDS = [
        "relay", "update", "app", "macos", "mac", "homebrew", "brew",
        "install", "download", "version", "bug", "feature", "crash",
        "error", "issue", "help", "question", "rollback", "backup",
        "обновление", "приложение", "баг", "ошибка", "установка",
        "скачать", "версия", "откат", "бэкап", "вопрос"
    ]
    
    # Offensive words (basic list, extend as needed)
    OFFENSIVE_PATTERNS = [
        r"\b(idiot|stupid|dumb|moron|loser)\b",
        r"\b(идиот|тупой|дурак|лох)\b",
    ]
    
    def __init__(self):
        self.user_message_times: dict[int, list[datetime]] = {}
    
    def analyze(self, text: str, user_id: int, username: str = "") -> AnalysisResult:
        """Analyze a message and return violation info"""
        
        text_lower = text.lower()
        
        # Check for spam patterns first (highest priority)
        spam_result = self._check_spam(text, text_lower)
        if spam_result:
            return spam_result
        
        # Check for flooding
        flood_result = self._check_flood(user_id)
        if flood_result:
            return flood_result
        
        # Check for harassment
        harassment_result = self._check_harassment(text_lower)
        if harassment_result:
            return harassment_result
        
        # Check for external links
        links_result = self._check_external_links(text)
        if links_result:
            return links_result
        
        # Check if off-topic (only if clearly not about Relay)
        offtopic_result = self._check_off_topic(text_lower)
        if offtopic_result:
            return offtopic_result
        
        # No violation detected
        return AnalysisResult(
            is_violation=False,
            violation_type=None,
            confidence=0.0,
            reason="Message appears to follow community rules",
            should_delete=False,
            should_warn=False,
            should_mute=False,
            should_ban=False
        )
    
    def _check_spam(self, text: str, text_lower: str) -> Optional[AnalysisResult]:
        """Check for spam patterns"""
        
        # Check regex patterns
        for pattern in SPAM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return AnalysisResult(
                    is_violation=True,
                    violation_type="spam",
                    confidence=0.95,
                    reason=f"Detected spam pattern: {pattern}",
                    should_delete=True,
                    should_warn=False,
                    should_mute=False,
                    should_ban=True
                )
        
        # Check suspicious keywords with high density
        suspicious_count = sum(1 for kw in SUSPICIOUS_KEYWORDS if kw in text_lower)
        if suspicious_count >= 3:
            return AnalysisResult(
                is_violation=True,
                violation_type="spam",
                confidence=0.8,
                reason=f"Multiple suspicious keywords detected ({suspicious_count})",
                should_delete=True,
                should_warn=False,
                should_mute=True,
                should_ban=False
            )
        
        # Check for excessive caps (shouting)
        if len(text) > 20:
            caps_ratio = sum(1 for c in text if c.isupper()) / len(text)
            if caps_ratio > 0.7:
                return AnalysisResult(
                    is_violation=True,
                    violation_type="spam",
                    confidence=0.6,
                    reason="Excessive use of capital letters",
                    should_delete=False,
                    should_warn=True,
                    should_mute=False,
                    should_ban=False
                )
        
        return None
    
    def _check_flood(self, user_id: int) -> Optional[AnalysisResult]:
        """Check for message flooding"""
        now = datetime.now()
        
        if user_id not in self.user_message_times:
            self.user_message_times[user_id] = []
        
        # Clean old entries
        self.user_message_times[user_id] = [
            t for t in self.user_message_times[user_id]
            if now - t < timedelta(minutes=1)
        ]
        
        # Add current message
        self.user_message_times[user_id].append(now)
        
        # Check flood
        from config import MAX_MESSAGES_PER_MINUTE
        if len(self.user_message_times[user_id]) > MAX_MESSAGES_PER_MINUTE:
            return AnalysisResult(
                is_violation=True,
                violation_type="flood",
                confidence=0.9,
                reason=f"Sending too many messages ({len(self.user_message_times[user_id])}/min)",
                should_delete=False,
                should_warn=False,
                should_mute=True,
                should_ban=False
            )
        
        return None
    
    def _check_harassment(self, text_lower: str) -> Optional[AnalysisResult]:
        """Check for harassment or insults"""
        
        for pattern in self.OFFENSIVE_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return AnalysisResult(
                    is_violation=True,
                    violation_type="harassment",
                    confidence=0.85,
                    reason="Offensive language detected",
                    should_delete=True,
                    should_warn=True,
                    should_mute=False,
                    should_ban=False
                )
        
        return None
    
    def _check_external_links(self, text: str) -> Optional[AnalysisResult]:
        """Check for unrelated external links"""
        
        # Find all URLs
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        
        if len(urls) > MAX_LINKS_PER_MESSAGE:
            return AnalysisResult(
                is_violation=True,
                violation_type="external_links",
                confidence=0.7,
                reason=f"Too many links ({len(urls)})",
                should_delete=True,
                should_warn=True,
                should_mute=False,
                should_ban=False
            )
        
        # Check if links are Relay-related
        allowed_domains = [
            "relay", "github.com/sunopiusme", "brew.sh", 
            "apple.com", "developer.apple.com", "t.me/relay"
        ]
        
        for url in urls:
            is_allowed = any(domain in url.lower() for domain in allowed_domains)
            if not is_allowed and "t.me" not in url:
                # External link, but might be relevant - low confidence
                return AnalysisResult(
                    is_violation=True,
                    violation_type="external_links",
                    confidence=0.5,
                    reason=f"External link detected: {url[:50]}...",
                    should_delete=False,
                    should_warn=True,
                    should_mute=False,
                    should_ban=False
                )
        
        return None
    
    def _check_off_topic(self, text_lower: str) -> Optional[AnalysisResult]:
        """Check if message is off-topic"""
        
        # If message is short, don't flag as off-topic
        if len(text_lower) < 30:
            return None
        
        # Check for Relay-related keywords
        relay_keyword_count = sum(1 for kw in self.RELAY_KEYWORDS if kw in text_lower)
        
        # If no Relay keywords and message is long, might be off-topic
        if relay_keyword_count == 0 and len(text_lower) > 100:
            # But only with low confidence - humans should review
            return AnalysisResult(
                is_violation=True,
                violation_type="off_topic",
                confidence=0.3,  # Low confidence - needs review
                reason="Message may be off-topic (no Relay-related keywords)",
                should_delete=False,
                should_warn=False,  # Don't auto-warn for off-topic
                should_mute=False,
                should_ban=False
            )
        
        return None
    
    def analyze_report(self, reported_text: str, reporter_reason: str) -> AnalysisResult:
        """Analyze a reported message with additional context from reporter"""
        
        # First do standard analysis
        result = self.analyze(reported_text, user_id=0)
        
        # If standard analysis found violation, return it
        if result.is_violation and result.confidence > 0.7:
            return result
        
        # Analyze reporter's reason
        reason_lower = reporter_reason.lower()
        
        harassment_keywords = ["harass", "insult", "rude", "offensive", "attack",
                              "оскорб", "грубо", "хамство", "атака"]
        spam_keywords = ["spam", "ad", "promo", "scam", "спам", "реклама"]
        offtopic_keywords = ["off-topic", "unrelated", "не по теме", "оффтоп"]
        
        if any(kw in reason_lower for kw in harassment_keywords):
            return AnalysisResult(
                is_violation=True,
                violation_type="harassment",
                confidence=0.6,
                reason=f"Reported for harassment: {reporter_reason}",
                should_delete=False,
                should_warn=True,
                should_mute=False,
                should_ban=False
            )
        
        if any(kw in reason_lower for kw in spam_keywords):
            return AnalysisResult(
                is_violation=True,
                violation_type="spam",
                confidence=0.6,
                reason=f"Reported as spam: {reporter_reason}",
                should_delete=True,
                should_warn=False,
                should_mute=True,
                should_ban=False
            )
        
        if any(kw in reason_lower for kw in offtopic_keywords):
            return AnalysisResult(
                is_violation=True,
                violation_type="off_topic",
                confidence=0.5,
                reason=f"Reported as off-topic: {reporter_reason}",
                should_delete=False,
                should_warn=True,
                should_mute=False,
                should_ban=False
            )
        
        # Can't determine - needs admin review
        return AnalysisResult(
            is_violation=False,
            violation_type=None,
            confidence=0.0,
            reason="Report requires admin review",
            should_delete=False,
            should_warn=False,
            should_mute=False,
            should_ban=False
        )
