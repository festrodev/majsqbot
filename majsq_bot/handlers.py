"""Telegram update handling.

The one rule that shapes this file: **in a group, stay quiet unless spoken to.**
A bot that answers every message in a busy group gets removed within the hour.
maj$q replies when it is mentioned, replied to, or when someone is clearly
asking the question it exists to answer — and otherwise says nothing at all.
"""

from __future__ import annotations

import logging
import os
import re
import time

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from majsq_bot import agent, render

logger = logging.getLogger(__name__)

BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").lstrip("@")

# What counts as "asking the question" in a group, in both languages. Kept
# deliberately narrow: a false positive is a bot barging into a conversation.
_INTENT = re.compile(
    r"\b(quoi faire|on fait quoi|des idées|what should we do|what'?s happening|"
    r"any ideas|ce soir|this weekend|tonight|sortir|go out)\b",
    re.I,
)

_GROUP_DEBOUNCE_SECONDS = 8
_AGENT_ERROR_COOLDOWN_SECONDS = 60
_LAST_GROUP_TURN: dict[int, float] = {}
_LAST_AGENT_ERROR: dict[int, float] = {}


def _locale(update: Update) -> str:
    code = (update.effective_user.language_code or "fr") if update.effective_user else "fr"
    return "fr" if code.startswith("fr") else "en"


def _kind(update: Update) -> str:
    chat = update.effective_chat
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return "group"
    return "dm"


def _addressed(update: Update) -> bool:
    """Is this group message for us?"""
    message = update.effective_message
    if not message:
        return False
    if _kind(update) == "dm":
        return True
    text = message.text or ""
    if BOT_USERNAME and f"@{BOT_USERNAME}".lower() in text.lower():
        return True
    reply_to = message.reply_to_message
    if reply_to and reply_to.from_user and reply_to.from_user.is_bot:
        return True
    return bool(_INTENT.search(text))


def _bare_mention(text: str) -> bool:
    return bool(BOT_USERNAME and text.strip().lower() == f"@{BOT_USERNAME}".lower())


def _allow_group_turn(chat_id: int) -> bool:
    now = time.monotonic()
    last_turn = _LAST_GROUP_TURN.get(chat_id)
    if last_turn is not None and now - last_turn < _GROUP_DEBOUNCE_SECONDS:
        return False
    _LAST_GROUP_TURN[chat_id] = now
    return True


def _should_report_agent_error(chat_id: int) -> bool:
    now = time.monotonic()
    last_error = _LAST_AGENT_ERROR.get(chat_id)
    if last_error is not None and now - last_error < _AGENT_ERROR_COOLDOWN_SECONDS:
        return False
    _LAST_AGENT_ERROR[chat_id] = now
    return True


async def _send_reply(update: Update, reply: dict, locale: str) -> None:
    message = update.effective_message
    if reply.get("question"):
        text, keyboard = render.question_message(reply["question"])
        await message.reply_text(text, reply_markup=keyboard)
        return

    if reply.get("picks"):
        text, keyboard = render.picks_message(reply, locale=locale)
        await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

        poll = reply.get("poll")
        if poll and len(poll.get("options", [])) >= 2:
            await message.reply_poll(
                question=poll["question"],
                options=poll["options"],
                is_anonymous=False,  # the group should see who is coming
            )
        return

    if reply.get("text"):
        await message.reply_text(reply["text"])


async def start(update: Update, _context) -> None:
    locale = _locale(update)
    await update.effective_message.reply_text(
        render.welcome(is_group=_kind(update) == "group", locale=locale),
        parse_mode=ParseMode.HTML,
    )
    await _turn(update, text="")


async def on_message(update: Update, _context) -> None:
    if not _addressed(update):
        return
    chat = update.effective_chat
    if _kind(update) == "group" and not _allow_group_turn(chat.id):
        return
    text = update.effective_message.text or ""
    await _turn(update, text="quoi faire ce soir ?" if _bare_mention(text) else text)


async def on_my_chat_member(update: Update, _context) -> None:
    """Welcome a group only when the bot has just been added to it."""
    membership = update.my_chat_member
    if not membership or _kind(update) != "group":
        return
    old_status = membership.old_chat_member.status
    new_status = membership.new_chat_member.status
    joined = old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED} and new_status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    }
    if joined:
        await update.effective_chat.send_message(
            render.welcome(is_group=True, locale=_locale(update)), parse_mode=ParseMode.HTML
        )


async def on_callback(update: Update, _context) -> None:
    """A tapped chip, or the taste-consent toggle."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    locale = _locale(update)

    if data.startswith("consent:"):
        enabled = data.split(":", 1)[1] == "on"
        try:
            now_on = await agent.set_consent(
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                kind=_kind(update),
                enabled=enabled,
                display_name=update.effective_user.first_name or "",
            )
        except agent.AgentError:
            logger.exception("consent toggle failed")
            return
        french = locale == "fr"
        if now_on:
            note = (
                "✅ Tes goûts comptent dans ce groupe." if french else "✅ Your taste counts here."
            )
        else:
            note = (
                "Tes goûts ne comptent plus ici." if french else "Your taste no longer counts here."
            )
        await query.edit_message_reply_markup(
            reply_markup=render.consent_keyboard(
                query.message.reply_markup, enabled=now_on, locale=locale
            )
        )
        await query.message.reply_text(note)
        return

    if data.startswith("ans:"):
        _, name, value = data.split(":", 2)
        await _turn(update, text="", chosen={name: value}, from_callback=True)


async def _turn(
    update: Update, *, text: str, chosen: dict | None = None, from_callback: bool = False
) -> None:
    locale = _locale(update)
    chat = update.effective_chat
    try:
        reply = await agent.turn(
            chat_id=chat.id,
            user_id=update.effective_user.id,
            kind=_kind(update),
            display_name=update.effective_user.first_name or "",
            locale=locale,
            title=(chat.title or "")[:200],
            text=text,
            chosen=chosen,
        )
    except agent.AgentError:
        logger.exception("agent turn failed")
        if _should_report_agent_error(chat.id):
            await update.effective_message.reply_text(
                "Je n'arrive pas à joindre mon cerveau 🧠 Réessaie dans une minute."
                if locale == "fr"
                else "I can't reach my brain 🧠 Try again in a minute."
            )
        return
    await _send_reply(update, reply, locale)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).updater(None).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(
        MessageHandler(filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, on_message)
    )
    return application
