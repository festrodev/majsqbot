# maj$q Telegram surface. Holds no model key and no Festro credentials — it
# turns Telegram updates into agent calls and replies into messages.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8080

# One worker on purpose. The webhook de-duplicates Telegram's retries in an
# in-process set (majsq_bot/app.py), so a second worker would have its own copy
# and a retried update could post a second set of picks to the group. Move that
# set to Redis before scaling this past 1.
CMD ["sh", "-c", "exec uvicorn majsq_bot.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
