#!/usr/bin/env python3
"""
Pyszne Slot Bot — Telegram Bot
Obsługuje komendy użytkowników: /start, /schedule, /zone, /pause, /resume, /status, /check, /mute
Konfiguracja zapisywana w GitHub Gist (prywatny).
"""

import json
import os
import base64
import logging
import requests
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

WARSAW_TZ = pytz.timezone("Europe/Warsaw")

# ── Stany konwersacji ─────────────────────────────────────────────────────────
(
    ASK_NAME,
    ASK_COURIER_ID,
    ASK_EMAIL,
    ASK_CITY,
    ASK_ZONE,
    ASK_DAYS,
    ASK_HOUR_FROM,
    ASK_HOUR_TO,
    ASK_MUTE_DURATION,
) = range(9)

# ── Dostępne miasta i strefy ──────────────────────────────────────────────────
CITIES_ZONES = {
    "Warszawa": [
        "Center-Mokotow-Srodmiejscie",
        "Praga-Polnoc",
        "Praga-Poludnie",
        "Ursynow-Wilanow",
        "Wola-Bemowo",
        "Zoliborz-Bielany",
        "Targowek-Rembertow",
    ],
    "Łódź": ["Centrum", "Bałuty", "Górna", "Polesie", "Widzew"],
    "Kraków": ["Stare Miasto", "Krowodrza", "Nowa Huta", "Podgórze"],
    "Wrocław": ["Centrum", "Krzyki", "Psie Pole", "Fabryczna"],
}

DAYS_PL = {
    1: "Pon", 2: "Wt", 3: "Śr", 4: "Czw", 5: "Pt", 6: "Sob", 7: "Nd"
}

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScb9idqew6_DKUuxw3Qlwi73F5TgsSb3Z6b2QU41egefYmfGw/viewform"

# ── GitHub Gist — baza danych ─────────────────────────────────────────────────
GIST_ID = os.environ.get("GIST_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def load_users_from_gist() -> dict:
    """Pobiera config użytkowników z GitHub Gist."""
    if not GIST_ID or not GITHUB_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GITHUB_TOKEN}"},
            timeout=10,
        )
        data = resp.json()
        content = data["files"]["users.json"]["content"]
        return json.loads(content)
    except Exception as e:
        log.error(f"Błąd ładowania Gist: {e}")
        return {}


def save_users_to_gist(users: dict) -> bool:
    """Zapisuje config użytkowników do GitHub Gist."""
    if not GIST_ID or not GITHUB_TOKEN:
        return False
    try:
        payload = {
            "files": {
                "users.json": {
                    "content": json.dumps(users, ensure_ascii=False, indent=2)
                }
            }
        }
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GITHUB_TOKEN}"},
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log.error(f"Błąd zapisu Gist: {e}")
        return False


def get_user(chat_id: str) -> dict | None:
    users = load_users_from_gist()
    return users.get(str(chat_id))


def save_user(chat_id: str, user_data: dict) -> bool:
    users = load_users_from_gist()
    users[str(chat_id)] = user_data
    return save_users_to_gist(users)


# ── Helpers ───────────────────────────────────────────────────────────────────
def days_to_str(days: list[int]) -> str:
    return ", ".join(DAYS_PL[d] for d in sorted(days))


def get_status_text(user: dict) -> str:
    now = datetime.now(WARSAW_TZ)
    active = user.get("active", True)
    mute_until = user.get("mute_until")
    
    status_icon = "✅" if active else "⏸️"
    mute_str = ""
    if mute_until:
        mute_dt = datetime.fromisoformat(mute_until)
        if now < mute_dt:
            mute_str = f"\n🔕 Wyciszony do: {mute_dt.strftime('%H:%M %d.%m')}"

    return (
        f"👤 <b>{user['name']}</b>\n"
        f"🆔 ID kuriera: {user['courier_id']}\n"
        f"📍 Strefa: {user['zone']}\n"
        f"📅 Dni: {days_to_str(user.get('days', [1,2,3,4,5,6,7]))}\n"
        f"🕐 Godziny: {user.get('hour_from', 7)}:00 – {user.get('hour_to', 22)}:00\n"
        f"{status_icon} Status: {'Aktywny' if active else 'Zatrzymany'}"
        f"{mute_str}"
    )


# ── Komendy ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)

    if user:
        await update.message.reply_text(
            f"👋 Cześć, <b>{user['name']}</b>! Twój profil już istnieje.\n\n"
            + get_status_text(user)
            + "\n\n📋 <b>Dostępne komendy:</b>\n"
            "/status — pokaż profil\n"
            "/schedule — zmień dni i godziny\n"
            "/zone — zmień strefę\n"
            "/check — sprawdź sloty teraz\n"
            "/pause — zatrzymaj powiadomienia\n"
            "/resume — wznów powiadomienia\n"
            "/mute — wycisz na X godzin\n"
            "/help — pomoc",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🍕 <b>Witaj w Pyszne Slot Monitor!</b>\n\n"
        "Będę Cię powiadamiać gdy pojawią się dostępne sloty do przejęcia.\n\n"
        "Zacznijmy konfigurację. Podaj swoje <b>imię i nazwisko</b> (tak jak w Pyszne):",
        parse_mode="HTML",
    )
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Imię: <b>{context.user_data['name']}</b>\n\n"
        "Teraz podaj swoje <b>ID kuriera</b> (znajdziesz w emailu od Pyszne):",
        parse_mode="HTML",
    )
    return ASK_COURIER_ID


async def ask_courier_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    courier_id = update.message.text.strip()
    if not courier_id.isdigit():
        await update.message.reply_text("❌ ID kuriera musi być liczbą. Spróbuj ponownie:")
        return ASK_COURIER_ID
    context.user_data["courier_id"] = courier_id
    await update.message.reply_text(
        f"✅ ID: <b>{courier_id}</b>\n\n"
        "Podaj swój <b>email Google</b> (używany do logowania w formularzu):",
        parse_mode="HTML",
    )
    return ASK_EMAIL


async def ask_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("❌ Niepoprawny email. Spróbuj ponownie:")
        return ASK_EMAIL
    context.user_data["email"] = email
    
    # Wybór miasta — klawiatura inline
    keyboard = [
        [InlineKeyboardButton(city, callback_data=f"city_{city}")]
        for city in CITIES_ZONES.keys()
    ]
    await update.message.reply_text(
        "🏙️ Wybierz <b>miasto</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ASK_CITY


async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    city = query.data.replace("city_", "")
    context.user_data["city"] = city

    zones = CITIES_ZONES.get(city, [])
    keyboard = [
        [InlineKeyboardButton(zone, callback_data=f"zone_{zone}")]
        for zone in zones
    ]
    await query.edit_message_text(
        f"✅ Miasto: <b>{city}</b>\n\n📍 Wybierz <b>strefę</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ASK_ZONE


async def ask_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    zone = query.data.replace("zone_", "")
    context.user_data["zone"] = zone
    context.user_data["selected_days"] = []

    keyboard = [
        [InlineKeyboardButton(f"☐ {name}", callback_data=f"day_{num}")]
        for num, name in DAYS_PL.items()
    ] + [[InlineKeyboardButton("✅ Gotowe", callback_data="days_done")]]

    await query.edit_message_text(
        f"✅ Strefa: <b>{zone}</b>\n\n"
        "📅 Wybierz <b>dni monitorowania</b> (kliknij żeby zaznaczyć):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ASK_DAYS


async def ask_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "days_done":
        selected = context.user_data.get("selected_days", [])
        if not selected:
            await query.answer("Wybierz przynajmniej jeden dzień!", show_alert=True)
            return ASK_DAYS
        await query.edit_message_text(
            f"✅ Dni: <b>{days_to_str(selected)}</b>\n\n"
            "🕐 Od której godziny monitorować? (np. <code>7</code> = 7:00)",
            parse_mode="HTML",
        )
        return ASK_HOUR_FROM

    day_num = int(query.data.replace("day_", ""))
    selected = context.user_data.get("selected_days", [])

    if day_num in selected:
        selected.remove(day_num)
    else:
        selected.append(day_num)
    context.user_data["selected_days"] = selected

    # Odśwież klawiaturę z zaznaczeniem
    keyboard = [
        [InlineKeyboardButton(
            f"{'☑' if num in selected else '☐'} {name}",
            callback_data=f"day_{num}"
        )]
        for num, name in DAYS_PL.items()
    ] + [[InlineKeyboardButton("✅ Gotowe", callback_data="days_done")]]

    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_DAYS


async def ask_hour_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(":00", "").replace(":30", "")
    if not text.isdigit() or not (0 <= int(text) <= 23):
        await update.message.reply_text("❌ Podaj godzinę jako liczbę (0-23):")
        return ASK_HOUR_FROM
    context.user_data["hour_from"] = int(text)
    await update.message.reply_text(
        f"✅ Od: <b>{text}:00</b>\n\n"
        "🕐 Do której godziny? (np. <code>22</code> = 22:00)",
        parse_mode="HTML",
    )
    return ASK_HOUR_TO


async def ask_hour_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(":00", "").replace(":30", "")
    if not text.isdigit() or not (0 <= int(text) <= 23):
        await update.message.reply_text("❌ Podaj godzinę jako liczbę (0-23):")
        return ASK_HOUR_TO

    hour_to = int(text)
    hour_from = context.user_data.get("hour_from", 7)
    if hour_to <= hour_from:
        await update.message.reply_text(f"❌ Musi być po {hour_from}:00. Spróbuj ponownie:")
        return ASK_HOUR_TO

    context.user_data["hour_to"] = hour_to
    chat_id = str(update.effective_chat.id)

    # Zapisz użytkownika
    user_data = {
        "name": context.user_data["name"],
        "courier_id": context.user_data["courier_id"],
        "email": context.user_data["email"],
        "city": context.user_data["city"],
        "zone": context.user_data["zone"],
        "days": sorted(context.user_data["selected_days"]),
        "hour_from": context.user_data["hour_from"],
        "hour_to": hour_to,
        "active": True,
        "mute_until": None,
        "chat_id": chat_id,
        "cookies_b64": "",  # Do uzupełnienia przez setup_cookies.py
        "notify_empty": False,
    }

    if save_user(chat_id, user_data):
        await update.message.reply_text(
            "🎉 <b>Profil zapisany!</b>\n\n"
            + get_status_text(user_data)
            + "\n\n⚠️ <b>Ostatni krok:</b> Musisz uruchomić skrypt <code>setup_cookies.py</code> "
            "żeby zalogować się do Google i zapisać sesję.\n\n"
            "Instrukcja w README.md.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ Błąd zapisu. Spróbuj ponownie /start")

    return ConversationHandler.END


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return
    await update.message.reply_text(get_status_text(user), parse_mode="HTML")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return
    user["active"] = False
    save_user(chat_id, user)
    await update.message.reply_text("⏸️ <b>Monitoring zatrzymany.</b>\nWpisz /resume żeby wznowić.", parse_mode="HTML")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return
    user["active"] = True
    user["mute_until"] = None
    save_user(chat_id, user)
    await update.message.reply_text("▶️ <b>Monitoring wznowiony!</b>", parse_mode="HTML")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔕 Na ile godzin wyciszyć powiadomienia?\n"
        "Wpisz liczbę, np. <code>2</code> = 2 godziny",
        parse_mode="HTML",
    )
    return ASK_MUTE_DURATION


async def ask_mute_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("❌ Podaj liczbę godzin (min. 1):")
        return ASK_MUTE_DURATION

    hours = int(text)
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        return ConversationHandler.END

    mute_until = datetime.now(WARSAW_TZ) + timedelta(hours=hours)
    user["mute_until"] = mute_until.isoformat()
    save_user(chat_id, user)

    await update.message.reply_text(
        f"🔕 Wyciszono na <b>{hours}h</b> (do {mute_until.strftime('%H:%M %d.%m')}).\n"
        "Wpisz /resume żeby odciczyć wcześniej.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cmd_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(city, callback_data=f"city_{city}")]
        for city in CITIES_ZONES.keys()
    ]
    await update.message.reply_text(
        "🏙️ Wybierz nowe <b>miasto</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ASK_CITY


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return ConversationHandler.END

    context.user_data.update(user)
    context.user_data["selected_days"] = list(user.get("days", []))

    keyboard = [
        [InlineKeyboardButton(
            f"{'☑' if num in context.user_data['selected_days'] else '☐'} {name}",
            callback_data=f"day_{num}"
        )]
        for num, name in DAYS_PL.items()
    ] + [[InlineKeyboardButton("✅ Gotowe", callback_data="days_done")]]

    await update.message.reply_text(
        "📅 Zmień <b>dni monitorowania</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return ASK_DAYS


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ręczne sprawdzenie slotów — triggeruje GitHub Actions workflow dispatch."""
    chat_id = str(update.effective_chat.id)
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Nie masz profilu. Wpisz /start")
        return

    repo = os.environ.get("GITHUB_REPO", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if not repo or not gh_token:
        await update.message.reply_text("⚠️ Manualne sprawdzenie niedostępne.")
        return

    await update.message.reply_text("🔍 Sprawdzam sloty... (może potrwać ~1 min)")

    # Trigger GitHub Actions workflow
    resp = requests.post(
        f"https://api.github.com/repos/{repo}/actions/workflows/check_slots.yml/dispatches",
        headers={"Authorization": f"token {gh_token}"},
        json={"ref": "main", "inputs": {"chat_id": chat_id}},
        timeout=10,
    )

    if resp.status_code == 204:
        await update.message.reply_text("✅ Sprawdzanie uruchomione! Dostaniesz powiadomienie za chwilę.")
    else:
        await update.message.reply_text("❌ Błąd uruchomienia. Spróbuj ponownie.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍕 <b>Pyszne Slot Monitor — Pomoc</b>\n\n"
        "<b>Komendy:</b>\n"
        "/start — rejestracja / reset profilu\n"
        "/status — pokaż swój profil\n"
        "/schedule — zmień dni i godziny monitorowania\n"
        "/zone — zmień strefę\n"
        "/check — sprawdź sloty teraz\n"
        "/pause — zatrzymaj powiadomienia\n"
        "/resume — wznów powiadomienia\n"
        "/mute — wycisz na X godzin\n"
        "/help — ta wiadomość\n\n"
        "<b>Jak to działa?</b>\n"
        "Bot sprawdza formularz Pyszne.pl co 10 minut "
        "i wysyła Ci powiadomienie gdy pojawią się sloty w Twojej strefie.",
        parse_mode="HTML",
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Anulowano. Wpisz /start żeby zacząć od nowa.")
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        raise ValueError("Brak TELEGRAM_TOKEN!")

    app = Application.builder().token(token).build()

    # Conversation handler dla rejestracji i ustawień
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("zone", cmd_zone),
            CommandHandler("schedule", cmd_schedule),
            CommandHandler("mute", cmd_mute),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_COURIER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_courier_id)],
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_email)],
            ASK_CITY: [CallbackQueryHandler(ask_city, pattern="^city_")],
            ASK_ZONE: [CallbackQueryHandler(ask_zone, pattern="^zone_")],
            ASK_DAYS: [CallbackQueryHandler(ask_days, pattern="^(day_|days_done)")],
            ASK_HOUR_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_hour_from)],
            ASK_HOUR_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_hour_to)],
            ASK_MUTE_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_mute_duration)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("help", cmd_help))

    log.info("Bot uruchomiony!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
