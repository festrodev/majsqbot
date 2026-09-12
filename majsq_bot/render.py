"""Turn an agent reply into Telegram messages and keyboards.

Rendering rules that are easy to get wrong and expensive to get wrong:

* **Never re-upload event artwork.** Festro's cover images are signed, expiring
  URLs licensed for Festro's own pages. maj$q sends text and links. A photo
  message here would be a licensing problem, not a design choice.
* **One message per answer.** Three picks arrive as a single message with an
  inline keyboard, not as three messages — a group chat punishes anything that
  floods it, and a single message is what someone can forward.
* **A group answer discloses nothing personal.** The agent already strips
  reasons down to aggregates for groups; this module must not add anything back
  (no "Ali a réservé…", no member names next to picks).
"""

from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

_FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MONTHS = [
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
]


def when_label(pick: dict, *, locale: str = "fr") -> str:
    """Human time for a pick, honouring Festro's unknown-start-time flag."""
    raw = pick.get("start_datetime")
    if not raw:
        return ""
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    french = str(locale).startswith("fr")
    if french:
        day = f"{_FR_DAYS[start.weekday()]} {start.day} {_FR_MONTHS[start.month - 1]}"
    else:
        day = start.strftime("%a %-d %b")
    # start_time_known=False means Festro has a date but no confirmed hour.
    # Showing "00:00" there would be inventing a fact the source never gave.
    if pick.get("start_time_known") is False:
        return day
    return f"{day} · {start.strftime('%H:%M')}"


def price_label(pick: dict, *, locale: str = "fr") -> str:
    if pick.get("is_free"):
        return "Gratuit" if str(locale).startswith("fr") else "Free"
    return ""


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def picks_message(reply: dict, *, locale: str = "fr") -> tuple[str, InlineKeyboardMarkup]:
    """One message carrying every pick, plus the buttons under it."""
    french = str(locale).startswith("fr")
    lines = [f"<b>{_escape(reply.get('text', ''))}</b>", ""]

    for index, pick in enumerate(reply.get("picks", []), start=1):
        bits = [when_label(pick, locale=locale), pick.get("venue_name") or "", price_label(pick, locale=locale)]
        meta = " · ".join(bit for bit in bits if bit)
        lines.append(f"<b>{index}. {_escape(pick.get('title', ''))}</b>")
        if meta:
            lines.append(f"   {_escape(meta)}")
        if pick.get("why"):
            lines.append(f"   <i>{_escape(pick['why'])}</i>")
        lines.append("")

    rows: list[list[InlineKeyboardButton]] = []
    for index, pick in enumerate(reply.get("picks", []), start=1):
        if pick.get("url"):
            rows.append([InlineKeyboardButton(f"{index}. {pick.get('title', '')[:28]}", url=pick["url"])])

    if reply.get("map_url"):
        rows.append(
            [
                InlineKeyboardButton(
                    "🗺 Ouvrir sur la carte" if french else "🗺 Open the map",
                    url=reply["map_url"],
                )
            ]
        )

    # Persistent, reversible, and as easy to switch off as on — the label says
    # taste, never attendance. Attendance is the poll.
    rows.append(
        [
            InlineKeyboardButton(
                "🙋 Utiliser mes goûts ici" if french else "🙋 Use my taste here",
                callback_data="consent:on",
            )
        ]
    )

    if reply.get("suggest_connect"):
        lines.append(
            "💡 Connecte ton compte Festro pour des choix qui te ressemblent."
            if french
            else "💡 Connect your Festro account for picks that fit you."
        )

    return "\n".join(lines).strip(), InlineKeyboardMarkup(rows)


def question_message(question: dict) -> tuple[str, InlineKeyboardMarkup]:
    """A clarifying question as tappable chips, two per row."""
    options = question.get("options", [])
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(options), 2):
        rows.append(
            [
                InlineKeyboardButton(
                    option["label"],
                    callback_data=f"ans:{question['name']}:{option['value']}",
                )
                for option in options[i : i + 2]
            ]
        )
    return question.get("question", ""), InlineKeyboardMarkup(rows)


def welcome(*, is_group: bool, locale: str = "fr", bot_username: str = "") -> str:
    french = str(locale).startswith("fr")
    if is_group and french:
        return (
            "Salut 👋 Je suis <b>maj$q</b>.\n\n"
            "Demandez-moi <i>« quoi faire ce soir ? »</i> et je propose trois vraies "
            "sorties à Montréal, avec un sondage pour trancher et une carte.\n\n"
            "Chacun peut me connecter à son compte Festro en privé, puis toucher "
            "<b>🙋 Utiliser mes goûts ici</b> pour que ses goûts comptent dans ce groupe."
        )
    if is_group:
        return (
            "Hi 👋 I'm <b>maj$q</b>.\n\n"
            "Ask me <i>\"what should we do tonight?\"</i> and I'll suggest three real "
            "things happening in Montréal, with a poll to settle it and a map.\n\n"
            "Anyone can connect their Festro account in a DM, then tap "
            "<b>🙋 Use my taste here</b> so their taste counts in this group."
        )
    if french:
        return (
            "Salut 👋 Je suis <b>maj$q</b>.\n\n"
            "Dis-moi quand tu sors et ce qui te tente, et je te trouve trois vraies "
            "sorties à Montréal.\n\n"
            "Ajoute-moi à un groupe pour planifier à plusieurs."
        )
    return (
        "Hi 👋 I'm <b>maj$q</b>.\n\n"
        "Tell me when you're going out and what you're after, and I'll find three "
        "real things happening in Montréal.\n\n"
        "Add me to a group to plan together."
    )
