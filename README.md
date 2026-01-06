# 🚔 Relay Guard Bot

Autonomous moderation bot for Relay community chat. Keeps the community safe and friendly.

## Features

- **Real-time monitoring** - Analyzes messages for spam, harassment, and rule violations
- **Smart detection** - Uses pattern matching and keyword analysis with confidence scoring
- **Graduated punishment** - Warn → Mute → Ban escalation system
- **Manual reports** - `/report` command for community-driven moderation
- **Admin controls** - Override commands for manual moderation
- **Violation tracking** - Full history of violations per user

## Setup

### 1. Create the bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token

### 2. Add bot to group

1. Add the bot to your group
2. Make it an admin with permissions:
   - Delete messages
   - Ban users
   - Restrict members

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your bot token and group ID
```

### 4. Install & Run

```bash
pip install -r requirements.txt
python relay_guard_bot.py
```

## Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Show bot info |
| `/rules` | Display community rules |
| `/report` | Report a message (reply to it) |
| `/mystatus` | Check your violation history |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/stats` | Moderation statistics |
| `/pending` | View pending reports |
| `/review <id> <action>` | Handle a report |
| `/warn` | Warn a user (reply) |
| `/mute` | Mute a user (reply) |
| `/ban` | Ban a user (reply) |

## How Reports Work

1. User replies to a problematic message with `/report <reason>`
2. Bot analyzes the message
3. If high confidence violation → auto-action
4. If low confidence → queued for admin review
5. Admins notified via DM

## Violation Types

| Type | Severity | Default Action |
|------|----------|----------------|
| Spam | 5 | Ban |
| Harassment | 4 | Mute |
| External Links | 3 | Delete + Warn |
| Flood | 3 | Mute |
| Off-topic | 2 | Warn |
| Wrong Language | 1 | Warn |

## Configuration

Edit `config.py` to customize:

- `WARN_BEFORE_BAN` - Warnings before escalation (default: 3)
- `MUTE_DURATION_MINUTES` - Mute duration (default: 60)
- `BAN_DURATION_DAYS` - Ban duration, 0 = permanent (default: 7)
- `MAX_MESSAGES_PER_MINUTE` - Flood threshold (default: 10)
- `SPAM_PATTERNS` - Regex patterns for auto-ban
- `SUSPICIOUS_KEYWORDS` - Keywords that trigger review

## Community Rules

```
⭐️🦙 Relay Community Chat – Rules

1. Stay on-topic (Relay only)
2. Be respectful – no harassment or insults
3. No spam or unrelated links
4. English or Russian only

Repeated violations = removal from group
```

## License

MIT - Part of the Relay project
