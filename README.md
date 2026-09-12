# majsqbot

The Telegram surface of **maj$q** — the agent that plans your night out from
inside your group chat.

Add it to a group, ask *"quoi faire ce soir ?"*, and it comes back with three
real events happening in Montréal, a poll to settle it, and a map.

Part of the [maj$q](https://github.com/festrodev/majsq) project, built at the
AI Tinkerers "Agents, Everywhere" hackathon, Montréal, 12 September 2026.

| Repo | What it is |
|---|---|
| [`majsq`](https://github.com/festrodev/majsq) | The agent. Brain, catalog access, conversation store, HTTP contract. |
| [`majsqweb`](https://github.com/festrodev/majsqweb) | The web surface. Next.js + CopilotKit. |
| **`majsqbot`** | This. Telegram. |

## What's in here, and what isn't

This repo is a **surface**. It turns Telegram updates into agent calls and agent
replies into messages and keyboards. It holds no model key, no Festro
credentials, and no ranking logic — those live in the agent, so that the web
and Telegram can never drift into recommending different things.

| File | What it does |
|---|---|
| `majsq_bot/app.py` | Webhook server. Secret-header check, update de-duplication. |
| `majsq_bot/handlers.py` | When to speak, and what to do with taps. |
| `majsq_bot/render.py` | Replies → Telegram messages and inline keyboards. |
| `majsq_bot/agent.py` | The only module that knows the agent exists. |

## Group behaviour

In a group it stays quiet unless it is **mentioned**, **replied to**, or someone
clearly asks the question it exists to answer ("quoi faire", "ce soir", "what
should we do"). A bot that answers everything gets removed within the hour.

Members connect their Festro account in a DM, then tap **🙋 Utiliser mes goûts
ici** to let their taste count *in that group*. It is reversible with the same
button, and group-facing reasons stay aggregate — "2 sur 3 aiment le jazz",
never a member's name or what they booked.

## Run it

The [agent](https://github.com/festrodev/majsq) must be running first. It works
offline with `FESTRO_MOCK=1`, so you need no Festro credentials.

```bash
cp .env.example .env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn majsq_bot.app:app --reload --port 8080
```

Then create a bot with [@BotFather](https://t.me/botfather) and:

1. **`/setprivacy` → Disable.** Without this the bot cannot read group
   messages and the whole group experience silently does nothing.
2. Put the token and a random `TELEGRAM_WEBHOOK_SECRET` in `.env`.
3. Expose port 8080 with a tunnel, then point Telegram at it:

```bash
./scripts_set_webhook.sh https://your-tunnel-url
```

MIT licensed.
