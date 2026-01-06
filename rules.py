"""
Community Rules for Relay Guard Bot
"""

RULES_EN = """
⭐️🦙 *Relay Community Chat – Rules & Purpose*

This group exists for:
• Bug reports and issues
• Feature requests
• Questions about Relay
• Helpful discussion around the app

🥺🙏 Please keep it focused and friendly.

*Rules:*
1. Stay on-topic (Relay only)
2. Be respectful – no harassment or insults
3. No spam or unrelated links
4. English or Russian only

Repeated violations will result in removal from the group.

😊🥰 Thanks for helping us improve Relay!
"""

RULES_RU = """
⭐️🦙 *Чат сообщества Relay – цель и правила*

Этот чат для:
• Сообщений о багах
• Предложений по функциям
• Вопросов по приложению
• Полезного обсуждения Relay

🥺🙏 Будьте вежливы и по делу.

*Правила:*
1. Только тема Relay и обновлений macOS-приложений
2. Уважение друг к другу – без оскорблений и харассмента
3. Без спама и оффтопных ссылок
4. Пишем на русском или английском

При неоднократных нарушениях — удаление из чата.

😊🥰 Спасибо, что помогаете улучшать Relay!
"""

RULES_COMBINED = f"{RULES_EN}\n————\n{RULES_RU}"

# Violation types and their severity (1-5)
VIOLATION_TYPES = {
    "spam": {
        "severity": 5,
        "description": "Spam or promotional content",
        "action": "ban"
    },
    "off_topic": {
        "severity": 2,
        "description": "Off-topic discussion",
        "action": "warn"
    },
    "harassment": {
        "severity": 4,
        "description": "Harassment or insults",
        "action": "mute"
    },
    "external_links": {
        "severity": 3,
        "description": "Unrelated external links",
        "action": "delete"
    },
    "wrong_language": {
        "severity": 1,
        "description": "Message not in English or Russian",
        "action": "warn"
    },
    "flood": {
        "severity": 3,
        "description": "Message flooding",
        "action": "mute"
    }
}
