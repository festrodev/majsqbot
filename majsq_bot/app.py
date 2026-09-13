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
@app.get("/healthz/")
async def healthz():
    # BOTH forms are registered on purpose. Cloud Run's underlying Knative
    # infrastructure reserves the bare "/healthz" path (no trailing slash) for
    # its own queue-proxy sidecar health probing — external requests to that
    # exact path never reach this container at all; Google's edge answers its
    # own 404 before the request ever arrives, for a service that is in fact
    # running perfectly. "/healthz/" (trailing slash) is not reserved and
    # passes through. See festrodev/majsq's majsq_agent/urls.py, which hit
    # this first. Keep the bare path registered too, since anything calling
    # this from inside the same Cloud Run/Knative mesh (rather than over the
    # public internet) is unaffected and may already assume it exists.
    return {"ok": True, "service": "majsqbot", "configured": bool(TOKEN)}


@app.post("/tg/webhook/")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    # The secret is checked FIRST, before anything about our own configuration.
    # The other order leaks: an unsigned request to a misconfigured bot would
    # come back "TELEGRAM_BOT_TOKEN is not set", telling whoever found the URL
    # something about the deployment before proving they are Telegram.
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        # Deliberately 403, not 401: there is no credential to re-present.
        raise HTTPException(403, "bad secret token")
    if not application:
        raise HTTPException(503, "TELEGRAM_BOT_TOKEN is not set")

    payload = await request.json()
    update_id = payload.get("update_id")
    if isinstance(update_id, int) and _already_handled(update_id):
        # Telegram retried. Acknowledge so it stops, but do nothing again.
        return {"ok": True, "duplicate": True}

    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}
