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
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, ADMIN_IDS, MUTE_DURATION_MINUTES, BAN_DURATION_DAYS
from rules import RULES_COMBINED, VIOLATION_TYPES
from analyzer import MessageAnalyzer, AnalysisResult
from violations import (
    Violation, Report, record_violation, get_user_violations,
    should_escalate, record_report, get_pending_reports,
    update_report_status, get_stats
)


# Initialize analyzer
analyzer = MessageAnalyzer()

# Store for report context (message being reported)
pending_report_context: dict[int, dict] = {}


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
    
    # Skip messages from admins
    if update.effective_user.id in ADMIN_IDS:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    text = update.message.text
    
    # Analyze message
    result = analyzer.analyze(text, user_id, username)
    
    # Only act on high-confidence violations
    if result.is_violation and result.confidence >= 0.6:
        await take_action(update, context, result, user_id, username, text)


# === COMMANDS ===
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🚔 *Relay Guard Bot*\n\n"
        "I help keep the Relay community safe and friendly.\n\n"
        "*Commands:*\n"
        "/rules - Show community rules\n"
        "/report - Report a message (reply to it)\n"
        "/mystatus - Check your violation history\n\n"
        "*Admin commands:*\n"
        "/stats - Moderation statistics\n"
        "/pending - View pending reports\n"
        "/warn @user - Warn a user\n"
        "/mute @user - Mute a user\n"
        "/ban @user - Ban a user",
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
    """Show user's violation history"""
    user_id = update.effective_user.id
    data = get_user_violations(user_id)
    
    if not data.get("violations"):
        await update.message.reply_text(
            "✅ *Clean Record*\n\n"
            "You have no violations. Keep it up! 🎉",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await update.message.reply_text(
        f"📊 *Your Status*\n\n"
        f"Warnings: {data.get('warnings', 0)}\n"
        f"Mutes: {data.get('mutes', 0)}\n"
        f"Bans: {data.get('bans', 0)}\n\n"
        f"Total violations: {len(data.get('violations', []))}\n\n"
        f"_Please follow community rules to avoid further action._",
        parse_mode=ParseMode.MARKDOWN
    )


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
        await update.message.reply_text("✅ No pending reports!")
        return
    
    text = "📋 *Pending Reports*\n\n"
    for r in reports[:10]:  # Show max 10
        text += (
            f"*#{r['id']}* - @{r['reported_username']}\n"
            f"Reason: {r['reason'][:50]}\n"
            f"By: @{r['reporter_username']}\n\n"
        )
    
    text += "_Use /review <id> <action> to handle_"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


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


# === MAIN ===
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set RELAY_GUARD_BOT_TOKEN!")
        print("   export RELAY_GUARD_BOT_TOKEN='token_from_botfather'")
        return
    
    print("🚔 Relay Guard Bot starting...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("mystatus", cmd_mystatus))
    
    # Admin commands
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("ban", cmd_ban))
    
    # Message handler (for auto-moderation)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    
    print("🚔 Relay Guard Bot is now protecting the community!")
    print("   Commands: /start, /rules, /report, /mystatus")
    print("   Admin: /stats, /pending, /warn, /mute, /ban")
    
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
