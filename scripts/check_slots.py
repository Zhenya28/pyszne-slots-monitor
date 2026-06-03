#!/usr/bin/env python3
"""
Pyszne.pl Slot Checker v5 — Auto-accept tylko sobota min. 8h
"""

import json
import os
import sys
import time
import base64
import logging
import re
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
MIN_HOURS = 8


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
        return False
    mute = user.get("mute_until")
    if mute:
        mute_dt = datetime.fromisoformat(mute).astimezone(WARSAW_TZ)
        if now < mute_dt:
            return False
    return True


def parse_slot_hours(slot_text: str) -> float:
    match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', slot_text)
    if not match:
        return 0.0
    h1, m1, h2, m2 = int(match.group(1)), int(match.group(2)), \
                      int(match.group(3)), int(match.group(4))
    start_mins = h1 * 60 + m1
    end_mins = h2 * 60 + m2
    if end_mins < start_mins:
        end_mins += 24 * 60
    return (end_mins - start_mins) / 60.0


def get_slot_date(slot_text: str):
    """Zwraca obiekt datetime dla daty slotu lub None."""
    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', slot_text)
    if date_match:
        try:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = int(date_match.group(3))
            return datetime(year, month, day, tzinfo=WARSAW_TZ)
        except Exception:
            pass
    return None


def is_saturday(slot_text: str) -> bool:
    slot_date = get_slot_date(slot_text)
    if slot_date:
        return slot_date.isoweekday() == 6
    return False


def find_best_slot(slots: list) -> str | None:
    """Znajdź pierwszy slot który jest w sobotę i ma min. 8h."""
    for slot in slots:
        hours = parse_slot_hours(slot)
        slot_date = get_slot_date(slot)
        day_name = slot_date.strftime("%A") if slot_date else "?"
        log.info(f"Oceniam slot: '{slot}' → {hours:.1f}h, dzień: {day_name}")

        if hours < MIN_HOURS:
            log.info(f"  ❌ Za krótki ({hours:.1f}h)")
            continue

        if not is_saturday(slot):
            log.info(f"  ❌ Nie sobota ({day_name})")
            continue

        log.info(f"  ✅ PASUJE! Sobota, {hours:.1f}h")
        return slot

    return None


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
    raise Exception("Nie znaleziono Dalej/Next")


def click_radio(page, texts: list, timeout=25000):
    for text in texts:
        for sel in [
            f'div[role="radio"]:has-text("{text}")',
            f'label:has-text("{text}")',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click(timeout=timeout)
                    log.info(f"Kliknięto: {text}")
                    return True
            except Exception:
                continue
    raise Exception(f"Nie znaleziono radio: {texts}")


def click_submit(page) -> bool:
    """Próbuje kliknąć przycisk Wyślij/Submit/Prześlij."""
    submit_selectors = [
        'div[role="button"]:has-text("Prześlij")',
        'div[role="button"]:has-text("Submit")',
        'div[role="button"]:has-text("Wyślij")',
        'span:has-text("Prześlij")',
        'span:has-text("Submit")',
        'span:has-text("Wyślij")',
        'button[type="submit"]',
        'input[type="submit"]',
        '[jsname="M2UYVd"]',
        '[jsname="OCpkoe"]',
    ]
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click(timeout=15000)
                log.info(f"Kliknięto Wyślij: {sel}")
                time.sleep(3)
                return True
        except Exception:
            continue

    # Ostatnia deska ratunku — screenshot i szukaj po tekście
    log.warning("Próbuję znaleźć przycisk Wyślij przez evaluate...")
    try:
        page.evaluate("""
            const buttons = document.querySelectorAll('[role="button"], button');
            for (const btn of buttons) {
                const text = btn.innerText || btn.textContent || '';
                if (text.includes('Prześlij') || text.includes('Submit') || text.includes('Wyślij')) {
                    btn.click();
                    break;
                }
            }
        """)
        time.sleep(3)
        return True
    except Exception as e:
        log.error(f"Evaluate failed: {e}")

    return False


def check_and_accept(user: dict, playwright):
    """Przechodzi przez formularz i przyjmuje slot sobota min. 8h."""
    cookies = load_cookies(user.get("cookies_b64", ""))
    if not cookies:
        return None, []

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

    all_slots = []
    accepted_slot = None

    try:
        # Strona 1
        log.info(f"[{user['name']}] Ładuję formularz...")
        page.goto(FORM_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        try:
            email_inp = page.locator('input[type="email"]').first
            if email_inp.is_visible(timeout=5000):
                email_inp.fill(user["email"])
                time.sleep(0.5)
                click_next(page)
                time.sleep(3)
        except Exception:
            pass

        # Strona 2
        log.info(f"[{user['name']}] Dane kuriera...")
        time.sleep(2)
        text_inputs = page.locator('input[type="text"]').all()
        if len(text_inputs) >= 1:
            text_inputs[0].fill(user["name"])
        if len(text_inputs) >= 2:
            text_inputs[1].fill(str(user["courier_id"]))
        click_radio(page, ["2. Chcę przyjąć", "Chcę przyjąć"], timeout=30000)
        time.sleep(1)
        click_next(page)
        time.sleep(3)

        # Strona 3
        log.info(f"[{user['name']}] Miasto...")
        click_radio(page, [user["city"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # Strona 4
        log.info(f"[{user['name']}] Strefa...")
        click_radio(page, [user["zone"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # Strona 5 — sloty
        log.info(f"[{user['name']}] Czytam sloty...")
        time.sleep(2)

        # Otwórz dropdown
        for sel in ['[role="listbox"]', 'select', '[jsname]']:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click(timeout=5000)
                    time.sleep(1)
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
                        all_slots.append(text)
                        log.info(f"Slot dostępny: {text}")
                except Exception:
                    continue
            if all_slots:
                break

        if not all_slots:
            log.info(f"[{user['name']}] Brak slotów.")
            return None, []

        # Znajdź pasujący slot (sobota, min. 8h)
        best_slot = find_best_slot(all_slots)

        if not best_slot:
            log.info(f"[{user['name']}] Brak slotu sobota min. {MIN_HOURS}h.")
            return None, all_slots

        # Wybierz slot w dropdownie
        log.info(f"[{user['name']}] Wybieram: {best_slot}")
        for sel in ['[role="option"]', 'option', 'li[data-value]']:
            opts = page.locator(sel).all()
            for opt in opts:
                try:
                    if opt.inner_text().strip() == best_slot:
                        opt.click(timeout=5000)
                        log.info("Slot wybrany!")
                        time.sleep(1)
                        break
                except Exception:
                    continue
            break

        # Wyślij formularz
        log.info(f"[{user['name']}] Wysyłam formularz...")
        if click_submit(page):
            accepted_slot = best_slot
            log.info(f"[{user['name']}] ✅ Formularz wysłany!")
        else:
            log.error(f"[{user['name']}] ❌ Nie udało się wysłać formularza!")

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

    return accepted_slot, all_slots


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
            log.info(f"✅ Telegram → {chat_id}")
            return True
        log.error(f"Telegram błąd {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")
        return False


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

            accepted_slot, all_slots = check_and_accept(user, pw)

            if accepted_slot:
                hours = parse_slot_hours(accepted_slot)
                msg = (
                    f"🎉 <b>ZMIANA PRZYJĘTA AUTOMATYCZNIE!</b>\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"📍 Strefa: <b>{user['zone']}</b>\n"
                    f"✅ Slot: <b>{accepted_slot}</b>\n"
                    f"⏱️ Długość: <b>{hours:.1f}h</b>\n"
                    f"🕐 {datetime.now(WARSAW_TZ).strftime('%d.%m.%Y %H:%M')}\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f'<a href="{FORM_URL}">📝 Sprawdź formularz</a>'
                )
                send_telegram(token, user["chat_id"], msg)
            else:
                # Cisza — brak powiadomienia gdy nie ma pasującego slotu
                log.info(f"[{user['name']}] Brak pasującego slotu (sobota min. {MIN_HOURS}h).")

    log.info("Koniec sprawdzania.")


if __name__ == "__main__":
    main()
