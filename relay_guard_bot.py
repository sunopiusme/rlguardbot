#!/usr/bin/env python3
"""
🚔 Relay Guard Bot - Community Moderator

Autonomous moderation bot for Relay community chat.
Monitors messages, handles reports, and enforces community rules.

Features:
- Real-time message analysis
- /report command for manual reports
- Graduated punishment system (warn → mute → ban)
- Admin override commands
- Detailed logging and statistics

Setup:
  1. Create bot via @BotFather
  2. Add bot to group as admin (with ban/delete permissions)
  3. Set environment variables:
     export RELAY_GUARD_BOT_TOKEN="your_token"
     export RELAY_GROUP_ID="your_group_id"
  4. Run: python relay_guard_bot.py
"""

import asyncio
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from telegram.constants import ParseMode


# === KEEP-ALIVE SERVER ===
class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check endpoint for Render"""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Relay Guard Bot OK')
    
    def log_message(self, format, *args):
        pass  # Suppress logs


def start_health_server():
    """Start health check server in background thread"""
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"   Health server: http://0.0.0.0:{port}")

from config import (
    BOT_TOKEN, ADMIN_IDS, MUTE_DURATION_MINUTES, BAN_DURATION_DAYS,
    CAPTCHA_TIMEOUT_SECONDS, CAPTCHA_KICK_ON_FAIL,
    REP_COOLDOWN_SECONDS, REP_POINTS_MANUAL, DATA_DIR
)
try:
    from config import TEST_MODE
except ImportError:
    TEST_MODE = False

import json
import random
from rules import RULES_COMBINED, VIOLATION_TYPES
from analyzer import MessageAnalyzer, AnalysisResult
from violations import (
    Violation, Report, record_violation, get_user_violations,
    should_escalate, record_report, get_pending_reports,
    update_report_status, get_stats
)
from reputation import (
    rep_defend, rep_positive, rep_violation, rep_helpful,
    get_rep, get_leaderboard, add_rep, REP_HELPFUL_ANSWER
)


# Initialize analyzer
analyzer = MessageAnalyzer()

# Store for report context (message being reported)
pending_report_context: dict[int, dict] = {}

# Store for pending captchas {user_id: {"correct": int, "chat_id": int, "message_id": int, "timestamp": str}}
pending_captcha: dict[int, dict] = {}

# Store for rep cooldowns {giver_id: {receiver_id: timestamp}}
rep_cooldowns: dict[int, dict] = {}


def _load_json(filepath) -> dict:
    """Load JSON file or return empty dict"""
    if filepath.exists():
        with open(filepath, "r") as f:
            return json.load(f)
    return {}


def _save_json(filepath, data: dict):
    """Save dict to JSON file"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# === RESPONSE MESSAGES ===
MESSAGES = {
    "warn": "⚠️ *Warning* @{username}\n\n{reason}\n\nPlease follow the community rules. "
            "Repeated violations will result in mute or ban.",
    
    "mute": "🔇 *Muted* @{username} for {duration} minutes\n\n{reason}\n\n"
            "You have been temporarily muted for violating community rules.",
    
    "ban": "🚫 *Banned* @{username}\n\n{reason}\n\n"
           "You have been removed from the community for repeated violations.",
    
    "report_received": "📋 *Report Received*\n\n"
                       "Thank you for your report. Our team will review it shortly.\n"
                       "Report ID: #{report_id}",
    
    "report_actioned": "✅ *Report #{report_id} Actioned*\n\n"
                       "Action taken: {action}\nThank you for helping keep our community safe!",
    
    "report_dismissed": "ℹ️ *Report #{report_id} Reviewed*\n\n"
                        "After review, no action was taken. Thank you for your vigilance!",
    
    "no_violation": "✅ No violation detected in the reported message.",
    
    "admin_required": "🔒 This command is only available to admins.",
    
    "rules": RULES_COMBINED
}


# === MODERATION ACTIONS ===
async def warn_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    username: str,
    reason: str
):
    """Send a warning to user"""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=MESSAGES["warn"].format(username=username, reason=reason),
        parse_mode=ParseMode.MARKDOWN
    )


async def mute_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    username: str,
    reason: str,
    duration_minutes: int = MUTE_DURATION_MINUTES
):
    """Mute a user temporarily"""
    until_date = datetime.now() + timedelta(minutes=duration_minutes)
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=MESSAGES["mute"].format(
                username=username,
                reason=reason,
                duration=duration_minutes
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Failed to mute user {user_id}: {e}")


async def ban_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    username: str,
    reason: str
):
    """Ban a user from the group"""
    try:
        if BAN_DURATION_DAYS > 0:
            until_date = datetime.now() + timedelta(days=BAN_DURATION_DAYS)
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id,
                until_date=until_date
            )
        else:
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id
            )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=MESSAGES["ban"].format(username=username, reason=reason),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Failed to ban user {user_id}: {e}")


async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a message"""
    try:
        await update.message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")


async def take_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    result: AnalysisResult,
    user_id: int,
    username: str,
    message_text: str
):
    """Take appropriate action based on analysis result"""
    
    # TEST MODE: only warn, show what would happen
    if TEST_MODE:
        action_would_be = "warn"
        if result.should_ban:
            action_would_be = "ban"
        elif result.should_mute:
            action_would_be = "mute"
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🧪 TEST MODE\n\n"
                 f"@{username} would get: {action_would_be.upper()}\n"
                 f"Reason: {result.reason}\n"
                 f"Confidence: {result.confidence:.0%}\n\n"
                 f"(No action taken - test mode)"
        )
        return
    
    # Check if should escalate based on history
    should_esc, recommended = should_escalate(user_id)
    
    action_taken = "none"
    
    # Delete message if needed
    if result.should_delete:
        await delete_message(update, context)
    
    # Determine action (escalate if needed)
    if result.should_ban or (should_esc and recommended == "ban"):
        await ban_user(update, context, user_id, username, result.reason)
        action_taken = "ban"
    elif result.should_mute or (should_esc and recommended == "mute"):
        await mute_user(update, context, user_id, username, result.reason)
        action_taken = "mute"
    elif result.should_warn:
        await warn_user(update, context, user_id, username, result.reason)
        action_taken = "warn"
    
    # Record violation
    if action_taken != "none":
        violation = Violation(
            user_id=user_id,
            username=username,
            violation_type=result.violation_type or "unknown",
            reason=result.reason,
            message_text=message_text[:500],  # Truncate
            action_taken=action_taken,
            timestamp=datetime.now().isoformat(),
            confidence=result.confidence
        )
        record_violation(violation)


# === MESSAGE HANDLER ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and check for violations"""
    
    if not update.message or not update.message.text:
        return
    
    # Log chat ID for setup (remove after getting ID)
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        print(f"📍 Group detected: {chat.title} | ID: {chat.id}")
    
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    text = update.message.text
    
    # Check for +rep first
    if await handle_plus_rep(update, context):
        return  # Was a +rep message, don't process further
    
    # Test mode: /testme command allows admins to test on themselves
    if text.startswith("/testme "):
        test_text = text[8:]  # Remove "/testme "
        result = analyzer.analyze(test_text, user_id, username)
        
        response = f"🧪 TEST ANALYSIS\n\n"
        response += f"📝 Text: \"{test_text[:100]}\"\n\n"
        response += f"🚨 Violation: {'YES' if result.is_violation else 'NO'}\n"
        if result.is_violation:
            response += f"📋 Type: {result.violation_type}\n"
            response += f"📊 Confidence: {result.confidence:.0%}\n"
            response += f"💬 Reason: {result.reason}\n\n"
            response += f"Actions:\n"
            response += f"  Delete: {'✅' if result.should_delete else '❌'}\n"
            response += f"  Warn: {'✅' if result.should_warn else '❌'}\n"
            response += f"  Mute: {'✅' if result.should_mute else '❌'}\n"
            response += f"  Ban: {'✅' if result.should_ban else '❌'}"
        else:
            response += f"✅ Message is clean!"
        
        await update.message.reply_text(response)
        return
    
    # Skip messages from admins (normal mode)
    if update.effective_user.id in ADMIN_IDS:
        return
    
    # Analyze message
    result = analyzer.analyze(text, user_id, username)
    
    # Debug logging
    print(f"📝 Message from @{username}: \"{text[:50]}\"")
    print(f"   Violation: {result.is_violation}, Confidence: {result.confidence}, Type: {result.violation_type}")
    
    # Check if user is defending Relay (give +rep)
    if not result.is_violation and "relay" in text.lower():
        positive_words = ["love", "best", "great", "awesome", "amazing", "perfect", "excellent",
                         "люблю", "лучший", "круто", "супер", "отлично"]
        if any(word in text.lower() for word in positive_words):
            new_rep = rep_positive(user_id, username)
            print(f"   ⭐ +rep for positive feedback! Total: {new_rep}")
    
    # Only act on high-confidence violations
    if result.is_violation and result.confidence >= 0.6:
        print(f"   🚨 Taking action!")
        await take_action(update, context, result, user_id, username, text)


# === COMMANDS ===
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🚔 *Relay Guard Bot*\n\n"
        "I help keep the Relay Community safe and friendly.\n\n"
        "*Commands:*\n"
        "/rules — Community rules\n"
        "/report — Report a message (reply to it)\n"
        "/mystatus — Your reputation & history\n"
        "/rep — Check someone's reputation\n"
        "/top — Community leaderboard\n\n"
        "*How to earn reputation:*\n"
        "⭐ Get +rep from other members\n"
        "❤️ Say nice things about Relay\n"
        "💡 Help other users\n\n"
        "*To give +rep:*\n"
        "Reply to a message and type `+rep`",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show community rules"""
    await update.message.reply_text(
        MESSAGES["rules"],
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report command"""
    
    # Must be a reply to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "📋 *How to report:*\n\n"
            "1. Reply to the message you want to report\n"
            "2. Type `/report <reason>`\n\n"
            "Example: `/report spam advertising`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    reported_message = update.message.reply_to_message
    reported_user = reported_message.from_user
    reporter = update.effective_user
    
    # Get reason from command args
    reason = " ".join(context.args) if context.args else "No reason provided"
    
    # Don't allow self-reports
    if reported_user.id == reporter.id:
        await update.message.reply_text("❌ You cannot report yourself.")
        return
    
    # Don't allow reporting admins
    if reported_user.id in ADMIN_IDS:
        await update.message.reply_text("❌ You cannot report admins.")
        return
    
    # Analyze the reported message
    reported_text = reported_message.text or ""
    result = analyzer.analyze_report(reported_text, reason)
    
    # Create report
    report = Report(
        reporter_id=reporter.id,
        reporter_username=reporter.username or str(reporter.id),
        reported_user_id=reported_user.id,
        reported_username=reported_user.username or str(reported_user.id),
        reported_message=reported_text[:500],
        reason=reason,
        status="pending",
        timestamp=datetime.now().isoformat()
    )
    
    report_id = record_report(report)
    
    # If high confidence violation, take action immediately
    if result.is_violation and result.confidence >= 0.7:
        await take_action(
            update, context, result,
            reported_user.id,
            reported_user.username or str(reported_user.id),
            reported_text
        )
        update_report_status(report_id, "actioned", f"Auto-actioned: {result.reason}")
        
        await update.message.reply_text(
            MESSAGES["report_actioned"].format(
                report_id=report_id,
                action=result.violation_type
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Queue for admin review
        await update.message.reply_text(
            MESSAGES["report_received"].format(report_id=report_id),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📋 *New Report #{report_id}*\n\n"
                         f"Reporter: @{reporter.username}\n"
                         f"Reported: @{reported_user.username}\n"
                         f"Reason: {reason}\n\n"
                         f"Message: _{reported_text[:200]}_\n\n"
                         f"Analysis: {result.reason}\n"
                         f"Confidence: {result.confidence:.0%}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass


async def cmd_mystatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's reputation and violation history"""
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    
    # Get reputation
    rep_info = get_rep(user_id)
    violations = get_user_violations(user_id)
    
    badges_str = " ".join(rep_info["badges"]) if rep_info["badges"] else "None yet"
    
    text = f"📊 YOUR STATUS\n"
    text += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"👤 @{username}\n"
    text += f"🏆 Rank: {rep_info['rank']}\n"
    text += f"⭐ Reputation: {rep_info['total_rep']} pts\n"
    text += f"🎖️ Badges: {badges_str}\n\n"
    
    if violations.get("violations"):
        text += f"⚠️ Warnings: {violations.get('warnings', 0)}\n"
        text += f"🔇 Mutes: {violations.get('mutes', 0)}\n"
        text += f"🚫 Bans: {violations.get('bans', 0)}\n"
    else:
        text += f"✅ Clean record!\n"
    
    text += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    text += f"💡 Earn rep by helping others and defending Relay!"
    
    await update.message.reply_text(text)


async def cmd_rep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check someone's reputation (reply to their message)"""
    if not update.message.reply_to_message:
        # Show own rep
        await cmd_mystatus(update, context)
        return
    
    target = update.message.reply_to_message.from_user
    rep_info = get_rep(target.id)
    
    badges_str = " ".join(rep_info["badges"]) if rep_info["badges"] else "None"
    
    text = f"📊 @{target.username or target.id}\n"
    text += f"🏆 {rep_info['rank']} • ⭐ {rep_info['total_rep']} pts\n"
    text += f"🎖️ {badges_str}"
    
    await update.message.reply_text(text)


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show reputation leaderboard"""
    leaders = get_leaderboard(10)
    
    if not leaders:
        await update.message.reply_text("🏆 No reputation data yet!")
        return
    
    text = "🏆 RELAY COMMUNITY LEADERBOARD\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user in enumerate(leaders):
        medal = medals[i] if i < 3 else f"{i+1}."
        badges = " ".join(user["badges"][:2]) if user["badges"] else ""
        text += f"{medal} @{user['username']} — {user['total_rep']} pts {badges}\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "💡 /mystatus to see your rank"
    
    await update.message.reply_text(text)


# === ADMIN COMMANDS ===
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show moderation statistics (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    stats = get_stats()
    
    await update.message.reply_text(
        f"📊 *Moderation Statistics*\n\n"
        f"Users with violations: {stats['total_users_with_violations']}\n"
        f"Total violations: {stats['total_violations']}\n"
        f"├ Warnings: {stats['total_warnings']}\n"
        f"├ Mutes: {stats['total_mutes']}\n"
        f"└ Bans: {stats['total_bans']}\n\n"
        f"Reports: {stats['total_reports']}\n"
        f"└ Pending: {stats['pending_reports']}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending reports (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    reports = get_pending_reports()
    
    if not reports:
        await update.message.reply_text("✅ No pending reports! Community is clean.")
        return
    
    # Show each report with action buttons
    for r in reports[:5]:
        text = f"🔴 Report #{r['id']}\n\n"
        text += f"👤 User: @{r['reported_username']}\n"
        text += f"📝 Reason: {r['reason']}\n"
        text += f"👮 By: @{r['reporter_username']}\n\n"
        text += f"💬 Message:\n\"{r.get('reported_message', 'N/A')[:200]}\""
        
        keyboard = [
            [
                InlineKeyboardButton("⚠️ Warn", callback_data=f"review_{r['id']}_warn"),
                InlineKeyboardButton("🔇 Mute", callback_data=f"review_{r['id']}_mute"),
            ],
            [
                InlineKeyboardButton("🚫 Ban", callback_data=f"review_{r['id']}_ban"),
                InlineKeyboardButton("✅ Dismiss", callback_data=f"review_{r['id']}_dismiss"),
            ]
        ]
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def handle_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle review button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🔒 Admin only", show_alert=True)
        return
    
    # Parse callback data: review_1_warn
    parts = query.data.split("_")
    if len(parts) != 3:
        return
    
    _, report_id, action = parts
    report_id = int(report_id)
    
    if action == "dismiss":
        update_report_status(report_id, "dismissed", "Admin dismissed")
        await query.edit_message_text(
            f"✅ Report #{report_id} dismissed\n\n{query.message.text}"
        )
    else:
        update_report_status(report_id, "actioned", f"Admin action: {action}")
        
        action_emoji = {"warn": "⚠️", "mute": "🔇", "ban": "🚫"}.get(action, "✅")
        await query.edit_message_text(
            f"{action_emoji} Report #{report_id} → {action.upper()}\n\n{query.message.text}"
        )


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Review a report (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /review <report_id> <action>\n"
            "Actions: warn, mute, ban, dismiss"
        )
        return
    
    try:
        report_id = int(context.args[0])
        action = context.args[1].lower()
    except ValueError:
        await update.message.reply_text("Invalid report ID")
        return
    
    if action == "dismiss":
        update_report_status(report_id, "dismissed", "Admin dismissed")
        await update.message.reply_text(f"✅ Report #{report_id} dismissed")
    else:
        update_report_status(report_id, "actioned", f"Admin action: {action}")
        await update.message.reply_text(f"✅ Report #{report_id} actioned: {action}")


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually warn a user (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to warn the user")
        return
    
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "Admin warning"
    
    await warn_user(update, context, target.id, target.username or str(target.id), reason)
    
    violation = Violation(
        user_id=target.id,
        username=target.username or str(target.id),
        violation_type="admin_warn",
        reason=reason,
        message_text="",
        action_taken="warn",
        timestamp=datetime.now().isoformat(),
        confidence=1.0
    )
    record_violation(violation)


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually mute a user (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to mute the user")
        return
    
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "Admin mute"
    
    await mute_user(update, context, target.id, target.username or str(target.id), reason)
    
    violation = Violation(
        user_id=target.id,
        username=target.username or str(target.id),
        violation_type="admin_mute",
        reason=reason,
        message_text="",
        action_taken="mute",
        timestamp=datetime.now().isoformat(),
        confidence=1.0
    )
    record_violation(violation)


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually ban a user (admin only)"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(MESSAGES["admin_required"])
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to ban the user")
        return
    
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "Admin ban"
    
    await ban_user(update, context, target.id, target.username or str(target.id), reason)
    
    violation = Violation(
        user_id=target.id,
        username=target.username or str(target.id),
        violation_type="admin_ban",
        reason=reason,
        message_text="",
        action_taken="ban",
        timestamp=datetime.now().isoformat(),
        confidence=1.0
    )
    record_violation(violation)


# === WELCOME & CAPTCHA ===
WELCOME_PUZZLES = [
    {"q": "🍎 + 🍎 = ?", "a": 2, "options": [1, 2, 3, 4]},
    {"q": "🐱 How many legs does a cat have?", "a": 4, "options": [2, 3, 4, 6]},
    {"q": "🌈 Relay is a...", "a": 1, "options": ["📱 App", "🍕 Pizza", "🚗 Car"]},
    {"q": "🖥️ macOS is an...", "a": 0, "options": ["OS", "Browser", "Game"]},
    {"q": "1️⃣ + 2️⃣ = ?", "a": 3, "options": [2, 3, 4, 5]},
    {"q": "🍕 Pick the NOT food:", "a": 2, "options": ["🍔", "🍟", "💻", "🍩"]},
]


async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new members with a captcha puzzle"""
    
    for member in update.message.new_chat_members:
        # Skip bots
        if member.is_bot:
            continue
        
        user_id = member.id
        username = member.username or member.first_name or str(user_id)
        chat_id = update.effective_chat.id
        
        # Pick random puzzle
        puzzle = random.choice(WELCOME_PUZZLES)
        correct_idx = puzzle["options"].index(puzzle["a"]) if isinstance(puzzle["a"], str) else puzzle["a"]
        
        # For numeric answers, find the index
        if isinstance(puzzle["a"], int) and puzzle["a"] not in [0, 1, 2, 3]:
            # It's an actual number answer, find it in options
            correct_idx = puzzle["options"].index(puzzle["a"])
        
        # Create buttons
        buttons = []
        for i, opt in enumerate(puzzle["options"]):
            btn_text = str(opt)
            callback = f"captcha_{user_id}_{i}_{correct_idx}"
            buttons.append(InlineKeyboardButton(btn_text, callback_data=callback))
        
        keyboard = InlineKeyboardMarkup([buttons])
        
        # Restrict user until they solve captcha
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_other_messages=False
                )
            )
        except Exception as e:
            print(f"Could not restrict {user_id}: {e}")
        
        # Send welcome with puzzle
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"👋 Hey *{username}*!\n\n"
                 f"Welcome to Relay Community!\n\n"
                 f"🤖 Quick puzzle to get in:\n\n"
                 f"*{puzzle['q']}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
        # Store pending captcha
        pending_captcha[user_id] = {
            "correct": correct_idx,
            "chat_id": chat_id,
            "message_id": msg.message_id,
            "timestamp": datetime.now().isoformat(),
            "username": username
        }


async def handle_captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle captcha button clicks"""
    query = update.callback_query
    
    # Parse: captcha_{user_id}_{clicked}_{correct}
    parts = query.data.split("_")
    if len(parts) != 4:
        await query.answer("❌ Ошибка")
        return
    
    _, target_user_id, clicked, correct = parts
    target_user_id = int(target_user_id)
    clicked = int(clicked)
    correct = int(correct)
    
    # Only the target user can answer
    if query.from_user.id != target_user_id:
        await query.answer("🚫 This isn't your puzzle!", show_alert=True)
        return
    
    chat_id = query.message.chat_id
    username = pending_captcha.get(target_user_id, {}).get("username", "friend")
    
    if clicked == correct:
        # Correct! Unrestrict user
        await query.answer("✅ Correct!")
        
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
        except Exception as e:
            print(f"Could not unrestrict {target_user_id}: {e}")
        
        # Update message
        await query.edit_message_text(
            f"✅ *{username}* passed the check!\n\n"
            f"Welcome to Relay Community! 🎉\n\n"
            f"📋 /rules — community rules\n"
            f"⭐ /mystatus — your reputation\n"
            f"🏆 /top — leaderboard",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clean up
        if target_user_id in pending_captcha:
            del pending_captcha[target_user_id]
    else:
        # Wrong answer
        await query.answer("❌ Wrong! Try again", show_alert=True)


# === +REP SYSTEM ===
async def handle_plus_rep(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle +rep messages. Returns True if message was a +rep command.
    User replies to someone's message with "+rep" or "спасибо +rep" etc.
    """
    text = update.message.text.lower().strip()
    
    # Check if message contains +rep
    if "+rep" not in text and "+ rep" not in text:
        return False
    
    # Must be a reply
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "💡 To give +rep, reply to someone's message"
        )
        return True
    
    giver = update.effective_user
    receiver = update.message.reply_to_message.from_user
    
    # Can't give rep to yourself
    if giver.id == receiver.id:
        await update.message.reply_text("😅 Can't give +rep to yourself!")
        return True
    
    # Can't give rep to bots
    if receiver.is_bot:
        await update.message.reply_text("🤖 Bots don't need reputation!")
        return True
    
    # Check cooldown
    giver_cooldowns = rep_cooldowns.get(giver.id, {})
    last_rep_time = giver_cooldowns.get(receiver.id)
    
    if last_rep_time:
        last_time = datetime.fromisoformat(last_rep_time)
        elapsed = (datetime.now() - last_time).total_seconds()
        
        if elapsed < REP_COOLDOWN_SECONDS:
            remaining = int((REP_COOLDOWN_SECONDS - elapsed) / 60)
            await update.message.reply_text(
                f"⏳ You already gave +rep to this person recently.\n"
                f"Wait {remaining} more min."
            )
            return True
    
    # Give rep!
    receiver_username = receiver.username or receiver.first_name or str(receiver.id)
    new_rep = add_rep(
        receiver.id, 
        receiver_username, 
        REP_POINTS_MANUAL, 
        f"+rep от @{giver.username or giver.id}",
        "manual_rep"
    )
    
    # Update cooldown
    if giver.id not in rep_cooldowns:
        rep_cooldowns[giver.id] = {}
    rep_cooldowns[giver.id][receiver.id] = datetime.now().isoformat()
    
    # Get receiver's rank
    rep_info = get_rep(receiver.id)
    
    await update.message.reply_text(
        f"⭐ *+{REP_POINTS_MANUAL} rep* для @{receiver_username}!\n"
        f"Теперь у него {new_rep} очков ({rep_info['rank']})",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return True


# === MAIN ===
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set RELAY_GUARD_BOT_TOKEN!")
        print("   export RELAY_GUARD_BOT_TOKEN='token_from_botfather'")
        return
    
    print("🚔 Relay Guard Bot starting...")
    
    # Start health server for Render
    start_health_server()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("mystatus", cmd_mystatus))
    app.add_handler(CommandHandler("rep", cmd_rep))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("top", cmd_leaderboard))
    
    # Admin commands
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("ban", cmd_ban))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(handle_review_callback, pattern="^review_"))
    app.add_handler(CallbackQueryHandler(handle_captcha_callback, pattern="^captcha_"))
    
    # New member handler
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_member
    ))
    
    # Message handler (for auto-moderation and +rep)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    print("🚔 Relay Guard Bot is now protecting the community!")
    print("   Commands: /start, /rules, /report, /mystatus, /rep, /top")
    print("   Admin: /stats, /pending, /warn, /mute, /ban")
    print("   Features: +rep, welcome captcha")
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
