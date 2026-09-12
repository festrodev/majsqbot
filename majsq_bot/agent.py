"""The agent client.

This is the only module that knows the agent exists. Everything else in the bot
turns Telegram updates into calls here, and replies into Telegram messages.

The bot deliberately holds no model key, no Festro credentials, and no ranking
logic. If a decision about *what to recommend* ever appears in this repo, it is
in the wrong place: the same decision has to hold on the web too, and the only
way to guarantee that is to make one service own it.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

AGENT_URL = os.environ.get("MAJSQ_AGENT_URL", "http://localhost:8000").rstrip("/")
SERVICE_SECRET = os.environ.get("MAJSQ_SERVICE_SECRET", "")

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if SERVICE_SECRET:
        headers["X-Majsq-Service-Secret"] = SERVICE_SECRET
    return headers


class AgentError(RuntimeError):
    """The agent did not answer. The caller says so in the chat, once."""


async def turn(
    *,
    chat_id: int | str,
    user_id: int | str,
    kind: str,
    display_name: str = "",
    locale: str = "fr",
    title: str = "",
    text: str = "",
    chosen: dict | None = None,
) -> dict:
    """Advance the conversation and return the agent's reply payload.

    Identity comes from the Telegram update — the chat id and the user id that
    Telegram itself signed off on — never from anything a message body claims.
    """
    payload = {
        "channel": "telegram",
        "kind": kind,
        "conversation_id": str(chat_id),
        "participant_id": str(user_id),
        "display_name": display_name,
        "locale": locale,
        "title": title,
        "text": text,
    }
    if chosen:
        payload["chosen"] = chosen

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.post(f"{AGENT_URL}/api/turn/", json=payload, headers=_headers())
        except httpx.HTTPError as exc:
            raise AgentError(f"agent unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise AgentError(f"agent returned {response.status_code}: {response.text[:200]}")
    return response.json()


async def set_consent(
    *, chat_id: int | str, user_id: int | str, kind: str, enabled: bool, display_name: str = ""
) -> bool:
    """Toggle this member's taste consent for this chat."""
    payload = {
        "channel": "telegram",
        "kind": kind,
        "conversation_id": str(chat_id),
        "participant_id": str(user_id),
        "display_name": display_name,
        "use_my_taste": enabled,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{AGENT_URL}/api/consent/", json=payload, headers=_headers())
    if response.status_code >= 400:
        raise AgentError(f"consent failed: {response.status_code}")
    return bool(response.json().get("use_my_taste"))
