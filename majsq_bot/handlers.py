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

from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

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
    await _turn(update, text=update.effective_message.text or "")


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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return application
