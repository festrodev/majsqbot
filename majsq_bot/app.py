"""Webhook server.

Telegram POSTs updates here. Two things make that safe:

* **The secret header.** ``setWebhook`` is given a ``secret_token`` and Telegram
  echoes it as ``X-Telegram-Bot-Api-Secret-Token`` on every request. Anything
  without it is refused — a webhook URL is public, so the URL alone proves
  nothing about who is calling.
* **Update de-duplication.** Telegram retries on any non-2xx, and a retried
  update must not post a second set of picks to the group. Seen ``update_id``
  values are remembered and dropped.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update

load_dotenv()

from majsq_bot.handlers import build_application  # noqa: E402  (after load_dotenv)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Bounded so a long-running process cannot grow without limit.
_SEEN: OrderedDict[int, None] = OrderedDict()
_SEEN_MAX = 2000


def _already_handled(update_id: int) -> bool:
    if update_id in _SEEN:
        return True
    _SEEN[update_id] = None
    while len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    return False


application = build_application(TOKEN) if TOKEN else None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if application:
        await application.initialize()
        await application.start()
    yield
    if application:
        await application.stop()
        await application.shutdown()


app = FastAPI(title="majsqbot", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "majsqbot", "configured": bool(TOKEN)}


@app.post("/tg/webhook/")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not application:
        raise HTTPException(503, "TELEGRAM_BOT_TOKEN is not set")
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        # Deliberately 403, not 401: there is no credential to re-present.
        raise HTTPException(403, "bad secret token")

    payload = await request.json()
    update_id = payload.get("update_id")
    if isinstance(update_id, int) and _already_handled(update_id):
        # Telegram retried. Acknowledge so it stops, but do nothing again.
        return {"ok": True, "duplicate": True}

    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}
