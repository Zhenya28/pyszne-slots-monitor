#!/usr/bin/env python3
"""
Pyszne.pl Slot Checker v3
"""

import json
import os
import sys
import time
import base64
import logging
from datetime import datetime
import pytz
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScb9idqew6_DKUuxw3Qlwi73F5TgsSb3Z6b2QU41egefYmfGw/viewform"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
WARSAW_TZ = pytz.timezone("Europe/Warsaw")


def load_users() -> list:
    raw = os.environ.get("USERS_CONFIG", "")
    if not raw:
        log.error("Brak USERS_CONFIG!")
        sys.exit(1)
    try:
        users = json.loads(base64.b64decode(raw).decode("utf-8"))
        log.info(f"Załadowano {len(users)} użytkowników.")
        return users
    except Exception as e:
        log.error(f"Błąd USERS_CONFIG: {e}")
        sys.exit(1)


def load_cookies(b64: str) -> list:
    try:
        return json.loads(base64.b64decode(b64).decode("utf-8"))
    except Exception as e:
        log.error(f"Błąd cookies: {e}")
        return []


def should_run(user: dict) -> bool:
    now = datetime.now(WARSAW_TZ)
    if now.isoweekday() not in user.get("days", list(range(1, 8))):
        log.info(f"[{user['name']}] Nie dzisiaj.")
        return False
    h_from = int(user.get("hour_from", 7))
    h_to = int(user.get("hour_to", 22))
    if not (h_from <= now.hour < h_to):
        log.info(f"[{user['name']}] Poza oknem {h_from}-{h_to}.")
        return False
    if not user.get("active", True):
        log.info(f"[{user['name']}] Wyłączony.")
        return False
    mute = user.get("mute_until")
    if mute:
        mute_dt = datetime.fromisoformat(mute).astimezone(WARSAW_TZ)
        if now < mute_dt:
            log.info(f"[{user['name']}] Wyciszony do {mute_dt.strftime('%H:%M')}.")
            return False
    return True


def click_next(page):
    for sel in [
        'div[role="button"]:has-text("Dalej")',
        'div[role="button"]:has-text("Next")',
        'span:has-text("Dalej")',
        'span:has-text("Next")',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                btn.click(timeout=15000)
                return True
        except Exception:
            continue
    raise Exception("Nie znaleziono przycisku Dalej/Next")


def click_radio(page, texts: list, timeout=25000):
    for text in texts:
        for sel in [
            f'div[role="radio"]:has-text("{text}")',
            f'label:has-text("{text}")',
            f'[data-value="{text}"]',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click(timeout=timeout)
                    log.info(f"Kliknięto radio: {text}")
                    return True
            except Exception:
                continue
    raise Exception(f"Nie znaleziono radio dla: {texts}")


def get_slots(user: dict, playwright) -> list:
    log.info(f"[{user['name']}] Sprawdzam: {user['zone']}")

    cookies = load_cookies(user.get("cookies_b64", ""))
    if not cookies:
        log.error(f"[{user['name']}] Brak cookies!")
        return []

    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    context.add_cookies(cookies)
    page = context.new_page()
    slots = []

    try:
        # ── Strona 1: Email ───────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 1 — ładuję formularz...")
        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        try:
            email_inp = page.locator('input[type="email"]').first
            if email_inp.is_visible(timeout=5000):
                email_inp.fill(user["email"])
                time.sleep(0.5)
                click_next(page)
                time.sleep(3)
        except Exception as e:
            log.warning(f"[{user['name']}] Email step pominięty: {e}")

        # ── Strona 2: Dane kuriera ────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 2 — dane kuriera...")
        time.sleep(2)

        text_inputs = page.locator('input[type="text"]').all()
        if len(text_inputs) >= 1:
            text_inputs[0].fill(user["name"])
            time.sleep(0.3)
        if len(text_inputs) >= 2:
            text_inputs[1].fill(str(user["courier_id"]))
            time.sleep(0.3)

        # Radio "2. Chcę przyjąć" — dokładna nazwa z formularza
        log.info(f"[{user['name']}] Klikam 'Chcę przyjąć'...")
        click_radio(page, [
            "2. Chcę przyjąć",
            "Chcę przyjąć",
            "chcę przyjąć",
            "I want to accept the slot",
            "accept",
        ], timeout=30000)
        time.sleep(1)

        click_next(page)
        time.sleep(3)

        # ── Strona 3: Miasto ──────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 3 — miasto: {user['city']}")
        click_radio(page, [user["city"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # ── Strona 4: Strefa ──────────────────────────────────────────────────
        # Dokładna nazwa z formularza: "Center-Mokotow-Srodmiescie"
        log.info(f"[{user['name']}] Strona 4 — strefa: {user['zone']}")
        click_radio(page, [user["zone"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # ── Strona 5: Sloty ───────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 5 — czytam sloty...")
        time.sleep(2)

        # Loguj tekst strony dla debugowania
        page_text = page.inner_text("body")
        log.info(f"[{user['name']}] Strona 5 tekst:\n{page_text[:800]}")

        # Spróbuj otworzyć dropdown
        for sel in ['[role="listbox"]', 'select', '[jsname]']:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click(timeout=5000)
                    time.sleep(1)
                    log.info(f"[{user['name']}] Dropdown: {sel}")
                    break
            except Exception:
                continue

        # Zbierz opcje
        for sel in ['[role="option"]', 'option', 'li[data-value]']:
            opts = page.locator(sel).all()
            for opt in opts:
                try:
                    text = opt.inner_text().strip()
                    if text and text.lower() not in ["wybierz", "select", "--", "", "choose"]:
                        slots.append(text)
                        log.info(f"[{user['name']}] SLOT: {text}")
                except Exception:
                    continue
            if slots:
                break

        if not slots:
            log.info(f"[{user['name']}] Brak slotów.")

    except PlaywrightTimeout as e:
        log.error(f"[{user['name']}] Timeout: {e}")
    except Exception as e:
        log.error(f"[{user['name']}] Błąd: {e}")
    finally:
        try:
            page.close()
            context.close()
            browser.close()
        except Exception:
            pass

    return slots


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = TELEGRAM_API.format(token=token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"✅ Telegram wysłany → {chat_id}")
            return True
        log.error(f"Telegram błąd {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")
        return False


def format_message(user: dict, slots: list) -> str:
    now = datetime.now(WARSAW_TZ)
    lines = [
        "🔔 <b>DOSTĘPNE SLOTY PYSZNE.PL</b>",
        "━━━━━━━━━━━━━━━━━",
        f"📍 Strefa: <b>{user['zone']}</b>",
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}",
        "━━━━━━━━━━━━━━━━━",
    ]
    for s in slots:
        lines.append(f"✅ {s}")
    lines += [
        "━━━━━━━━━━━━━━━━━",
        f'<a href="{FORM_URL}">📝 Otwórz formularz</a>',
    ]
    return "\n".join(lines)


def main():
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        log.error("Brak TELEGRAM_TOKEN!")
        sys.exit(1)

    users = load_users()

    with sync_playwright() as pw:
        for user in users:
            log.info(f"\n{'='*50}\nUżytkownik: {user['name']}")
            if not should_run(user):
                continue

            slots = get_slots(user, pw)

            if slots:
                send_telegram(token, user["chat_id"], format_message(user, slots))
            else:
                log.info(f"[{user['name']}] Brak slotów o {datetime.now(WARSAW_TZ).strftime('%H:%M')}")
                if user.get("notify_empty"):
                    send_telegram(token, user["chat_id"], f"😴 Brak slotów — {user['zone']}")

    log.info("Koniec sprawdzania.")


if __name__ == "__main__":
    main()