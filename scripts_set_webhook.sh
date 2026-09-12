#!/usr/bin/env bash
# Point Telegram at this bot. Usage: ./scripts_set_webhook.sh https://your-tunnel.example
set -euo pipefail
[ -f .env ] && set -a && . ./.env && set +a
BASE="${1:?usage: $0 https://your-public-url}"
curl -sS -F "url=${BASE%/}/tg/webhook/" \
     -F "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
     -F "drop_pending_updates=true" \
     "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook"
echo
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
echo
