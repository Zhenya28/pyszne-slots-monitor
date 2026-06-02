#!/usr/bin/env python3
"""
Pyszne.pl Slot Checker
Sprawdza dostępne sloty w formularzu wymiany i powiadamia przez Telegram.
"""

import json
import os
import sys
import time
import pickle
import base64
import logging
from datetime import datetime, timezone
import pytz
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Stałe ────────────────────────────────────────────────────────────────────
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScb9idqew6_DKUuxw3Qlwi73F5TgsSb3Z6b2QU41egefYmfGw/viewform"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
WARSAW_TZ = pytz.timezone("Europe/Warsaw")

# ── Konfiguracja użytkowników (z GitHub Secrets / env) ───────────────────────
def load_users() -> list[dict]:
    """Ładuje użytkowników z env USERS_CONFIG (JSON base64)."""
    raw = os.environ.get("USERS_CONFIG", "")
    if not raw:
        log.error("Brak USERS_CONFIG w environment!")
        sys.exit(1)
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        users = json.loads(decoded)
        log.info(f"Załadowano {len(users)} użytkowników.")
        return users
    except Exception as e:
        log.error(f"Błąd parsowania USERS_CONFIG: {e}")
        sys.exit(1)


def load_cookies(b64_cookies: str) -> list[dict]:
    """Dekoduje cookies z base64 JSON."""
    try:
        decoded = base64.b64decode(b64_cookies).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        log.error(f"Błąd dekodowania cookies: {e}")
        return []


# ── Sprawdzanie harmonogramu ──────────────────────────────────────────────────
def should_run_for_user(user: dict) -> bool:
    """Sprawdza czy użytkownik powinien teraz dostać sprawdzenie."""
    now = datetime.now(WARSAW_TZ)
    weekday = now.isoweekday()  # 1=Pon, 7=Nd

    active_days = user.get("days", [1, 2, 3, 4, 5, 6, 7])
    if weekday not in active_days:
        log.info(f"[{user['name']}] Dzisiaj ({weekday}) nie jest dniem monitorowania.")
        return False

    hour_from = int(user.get("hour_from", 7))
    hour_to = int(user.get("hour_to", 22))
    current_hour = now.hour

    if not (hour_from <= current_hour < hour_to):
        log.info(f"[{user['name']}] Teraz {current_hour}:xx poza oknem {hour_from}-{hour_to}.")
        return False

    if not user.get("active", True):
        log.info(f"[{user['name']}] Monitoring wyłączony (/pause).")
        return False

    # Sprawdź mute
    mute_until = user.get("mute_until")
    if mute_until:
        mute_dt = datetime.fromisoformat(mute_until).astimezone(WARSAW_TZ)
        if now < mute_dt:
            log.info(f"[{user['name']}] Wyciszony do {mute_dt.strftime('%H:%M')}.")
            return False

    return True


# ── Playwright — scraping formularza ─────────────────────────────────────────
def get_slots_for_user(user: dict, playwright) -> list[str]:
    """
    Przechodzi przez formularz Pyszne.pl i zwraca listę dostępnych slotów
    dla danej strefy użytkownika.
    """
    log.info(f"[{user['name']}] Sprawdzam sloty dla strefy: {user['zone']}")

    cookies = load_cookies(user.get("cookies_b64", ""))
    if not cookies:
        log.error(f"[{user['name']}] Brak cookies — pomijam.")
        return []

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Wgrywamy cookies Google
    context.add_cookies(cookies)
    page = context.new_page()

    slots = []

    try:
        # ── Strona 1: Email ──────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 1 — ładuję formularz...")
        page.goto(FORM_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Wpisz email i kliknij Dalej
        email_input = page.locator('input[type="email"]')
        email_input.fill(user["email"])
        time.sleep(0.5)

        next_btn = page.locator('div[role="button"]:has-text("Dalej"), div[role="button"]:has-text("Next")')
        next_btn.first.click()
        time.sleep(2)

        # ── Strona 2: Imię, ID, opcja ────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 2 — dane kuriera...")

        # Imię Nazwisko
        name_input = page.locator('input[type="text"]').first
        name_input.fill(user["name"])
        time.sleep(0.3)

        # ID kuriera (drugie pole tekstowe)
        id_input = page.locator('input[type="text"]').nth(1)
        id_input.fill(str(user["courier_id"]))
        time.sleep(0.3)

        # Wybierz "Chcę przyjąć"
        accept_radio = page.locator('div[role="radio"]:has-text("Chcę przyjąć")')
        accept_radio.click()
        time.sleep(0.5)

        next_btn = page.locator('div[role="button"]:has-text("Dalej"), div[role="button"]:has-text("Next")')
        next_btn.first.click()
        time.sleep(2)

        # ── Strona 3: Miasto ─────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 3 — miasto: {user['city']}")
        city_radio = page.locator(f'div[role="radio"]:has-text("{user["city"]}")')
        city_radio.click()
        time.sleep(0.5)

        next_btn = page.locator('div[role="button"]:has-text("Dalej"), div[role="button"]:has-text("Next")')
        next_btn.first.click()
        time.sleep(2)

        # ── Strona 4: Strefa ─────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 4 — strefa: {user['zone']}")
        zone_radio = page.locator(f'div[role="radio"]:has-text("{user["zone"]}")')
        zone_radio.click()
        time.sleep(0.5)

        next_btn = page.locator('div[role="button"]:has-text("Dalej"), div[role="button"]:has-text("Next")')
        next_btn.first.click()
        time.sleep(2)

        # ── Strona 5: Dropdown ze slotami ────────────────────────────────────
        log.info(f"[{user['name']}] Strona 5 — odczytuję sloty z dropdownu...")

        # Kliknij dropdown żeby otworzyć opcje
        dropdown = page.locator('[role="listbox"], select, [data-params*="slot"]').first
        if not dropdown.is_visible():
            # Fallback — szukaj po aria
            dropdown = page.locator('[aria-label*="slot"], [aria-label*="Slot"]').first

        dropdown.click()
        time.sleep(1)

        # Zbierz wszystkie opcje
        options = page.locator('[role="option"]').all()
        for opt in options:
            text = opt.inner_text().strip()
            if text and text.lower() not in ["wybierz", "select", "--", ""]:
                slots.append(text)
                log.info(f"[{user['name']}] Znaleziony slot: {text}")

        if not slots:
            log.info(f"[{user['name']}] Brak dostępnych slotów.")

    except PlaywrightTimeout as e:
        log.error(f"[{user['name']}] Timeout podczas sprawdzania: {e}")
    except Exception as e:
        log.error(f"[{user['name']}] Błąd podczas sprawdzania: {e}")
    finally:
        page.close()
        context.close()
        browser.close()

    return slots


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Wysyła wiadomość przez Telegram Bot API."""
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            log.info(f"Telegram wysłany do chat_id={chat_id}")
            return True
        else:
            log.error(f"Telegram error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        log.error(f"Błąd wysyłania Telegram: {e}")
        return False


def format_slots_message(user: dict, slots: list[str]) -> str:
    """Formatuje wiadomość z dostępnymi slotami."""
    now = datetime.now(WARSAW_TZ)
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")

    lines = [
        "🔔 <b>DOSTĘPNE SLOTY PYSZNE.PL</b>",
        f"━━━━━━━━━━━━━━━━━",
        f"📍 Strefa: <b>{user['zone']}</b>",
        f"🕐 Sprawdzono: {date_str} o {time_str}",
        f"━━━━━━━━━━━━━━━━━",
    ]

    for slot in slots:
        lines.append(f"✅ {slot}")

    lines += [
        f"━━━━━━━━━━━━━━━━━",
        f'<a href="{FORM_URL}">📝 Otwórz formularz</a>',
    ]

    return "\n".join(lines)


def format_no_slots_message(user: dict) -> str:
    """Wiadomość gdy brak slotów — tylko do debug logu, nie wysyłamy na Telegram."""
    now = datetime.now(WARSAW_TZ)
    return f"[{user['name']}] Brak slotów o {now.strftime('%H:%M')}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    if not telegram_token:
        log.error("Brak TELEGRAM_TOKEN w environment!")
        sys.exit(1)

    users = load_users()

    with sync_playwright() as playwright:
        for user in users:
            log.info(f"\n{'='*50}")
            log.info(f"Przetwarzam użytkownika: {user['name']}")

            if not should_run_for_user(user):
                continue

            slots = get_slots_for_user(user, playwright)

            if slots:
                msg = format_slots_message(user, slots)
                send_telegram(telegram_token, user["chat_id"], msg)
            else:
                log.info(format_no_slots_message(user))
                # Opcjonalnie — wysyłaj "brak slotów" tylko jeśli user chce
                if user.get("notify_empty", False):
                    msg = f"😴 Brak slotów dla strefy <b>{user['zone']}</b>"
                    send_telegram(telegram_token, user["chat_id"], msg)

    log.info("\nSprawdzanie zakończone.")


if __name__ == "__main__":
    main()
