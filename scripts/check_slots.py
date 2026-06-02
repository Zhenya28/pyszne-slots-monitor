#!/usr/bin/env python3
"""
Pyszne.pl Slot Checker v4 — Auto-accept
Sprawdza sloty, filtruje min. 8h, automatycznie przyjmuje pierwszy pasujący.
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

MIN_HOURS = 8  # Minimalna długość zmiany w godzinach


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
            log.info(f"[{user['name']}] Wyciszony.")
            return False
    return True


def parse_slot_hours(slot_text: str) -> float:
    """
    Parsuje tekst slotu i zwraca długość w godzinach.
    Przykłady:
      "02.06.2026: 17:30-21:30 Center-Mokotow" → 4.0
      "03.06.2026: 07:00-15:00 ..." → 8.0
      "04.06.2026: 08:00-00:45 ..." → 16.75
    """
    # Szukaj wzorca HH:MM-HH:MM
    match = re.search(r'(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})', slot_text)
    if not match:
        return 0.0

    h1, m1, h2, m2 = int(match.group(1)), int(match.group(2)), \
                      int(match.group(3)), int(match.group(4))

    start_mins = h1 * 60 + m1
    end_mins = h2 * 60 + m2

    # Jeśli koniec < start — slot przechodzi przez północ (np. 22:00-00:45)
    if end_mins < start_mins:
        end_mins += 24 * 60

    duration = (end_mins - start_mins) / 60.0
    return duration


def is_saturday_slot(slot_text: str) -> bool:
    """Sprawdza czy slot jest w sobotę."""
    now = datetime.now(WARSAW_TZ)
    # Szukaj daty w tekście (DD.MM.YYYY lub MM/DD/YYYY)
    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', slot_text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3))
        try:
            slot_date = datetime(year, month, day, tzinfo=WARSAW_TZ)
            return slot_date.isoweekday() == 6  # 6 = Sobota
        except Exception:
            pass
    return True  # Jeśli nie możemy sprawdzić, zakładamy że OK


def find_best_slot(slots: list, require_saturday: bool = False) -> str | None:
    """
    Znajduje pierwszy slot spełniający kryteria:
    - min. MIN_HOURS godzin
    - opcjonalnie: tylko sobota
    """
    for slot in slots:
        hours = parse_slot_hours(slot)
        log.info(f"Slot: '{slot}' → {hours:.1f}h")

        if hours < MIN_HOURS:
            log.info(f"  ❌ Za krótki ({hours:.1f}h < {MIN_HOURS}h)")
            continue

        if require_saturday and not is_saturday_slot(slot):
            log.info(f"  ❌ Nie sobota")
            continue

        log.info(f"  ✅ Pasuje! ({hours:.1f}h)")
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
    raise Exception("Nie znaleziono przycisku Dalej/Next")


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
                    log.info(f"Kliknięto radio: {text}")
                    return True
            except Exception:
                continue
    raise Exception(f"Nie znaleziono radio dla: {texts}")


def check_and_accept_slot(user: dict, playwright, require_saturday: bool = False):
    """
    Przechodzi przez formularz, sprawdza sloty i jeśli znajdzie pasujący —
    automatycznie go przyjmuje (wysyła formularz).
    
    Zwraca: (accepted_slot, all_slots) lub (None, all_slots)
    """
    log.info(f"[{user['name']}] Sprawdzam: {user['zone']}")

    cookies = load_cookies(user.get("cookies_b64", ""))
    if not cookies:
        log.error(f"[{user['name']}] Brak cookies!")
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
            log.warning(f"[{user['name']}] Email pominięty: {e}")

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

        click_radio(page, ["2. Chcę przyjąć", "Chcę przyjąć"], timeout=30000)
        time.sleep(1)
        click_next(page)
        time.sleep(3)

        # ── Strona 3: Miasto ──────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 3 — miasto...")
        click_radio(page, [user["city"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # ── Strona 4: Strefa ──────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 4 — strefa...")
        click_radio(page, [user["zone"]], timeout=20000)
        time.sleep(0.5)
        click_next(page)
        time.sleep(3)

        # ── Strona 5: Sloty ───────────────────────────────────────────────────
        log.info(f"[{user['name']}] Strona 5 — czytam sloty...")
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
                        log.info(f"[{user['name']}] Slot dostępny: {text}")
                except Exception:
                    continue
            if all_slots:
                break

        if not all_slots:
            log.info(f"[{user['name']}] Brak slotów.")
            return None, []

        # ── Znajdź pasujący slot ──────────────────────────────────────────────
        best_slot = find_best_slot(all_slots, require_saturday=require_saturday)

        if not best_slot:
            log.info(f"[{user['name']}] Brak slotu spełniającego kryteria (min. {MIN_HOURS}h).")
            return None, all_slots

        # ── Wybierz slot w dropdownie ─────────────────────────────────────────
        log.info(f"[{user['name']}] Wybieram slot: {best_slot}")

        # Kliknij opcję z pasującym tekstem
        for sel in ['[role="option"]', 'option', 'li[data-value]']:
            opts = page.locator(sel).all()
            for opt in opts:
                try:
                    if opt.inner_text().strip() == best_slot:
                        opt.click(timeout=5000)
                        log.info(f"[{user['name']}] Slot wybrany!")
                        time.sleep(1)
                        break
                except Exception:
                    continue
            break

        # ── Wyślij formularz ──────────────────────────────────────────────────
        log.info(f"[{user['name']}] Wysyłam formularz...")

        for sel in [
            'div[role="button"]:has-text("Prześlij")',
            'div[role="button"]:has-text("Submit")',
            'div[role="button"]:has-text("Wyślij")',
            'span:has-text("Prześlij")',
            'span:has-text("Submit")',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn.click(timeout=15000)
                    time.sleep(3)
                    log.info(f"[{user['name']}] ✅ Formularz wysłany!")
                    accepted_slot = best_slot
                    break
            except Exception:
                continue

        if not accepted_slot:
            log.error(f"[{user['name']}] Nie znaleziono przycisku Wyślij!")

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
            log.info(f"✅ Telegram wysłany → {chat_id}")
            return True
        log.error(f"Telegram błąd {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")
        return False


def format_accepted_message(user: dict, slot: str) -> str:
    now = datetime.now(WARSAW_TZ)
    hours = parse_slot_hours(slot)
    return (
        f"🎉 <b>ZMIANA PRZYJĘTA AUTOMATYCZNIE!</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📍 Strefa: <b>{user['zone']}</b>\n"
        f"✅ Slot: <b>{slot}</b>\n"
        f"⏱️ Długość: <b>{hours:.1f}h</b>\n"
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"<a href=\"{FORM_URL}\">📝 Sprawdź formularz</a>"
    )


def format_found_message(user: dict, slots: list) -> str:
    now = datetime.now(WARSAW_TZ)
    lines = [
        "🔔 <b>DOSTĘPNE SLOTY PYSZNE.PL</b>",
        "━━━━━━━━━━━━━━━━━",
        f"📍 Strefa: <b>{user['zone']}</b>",
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}",
        "━━━━━━━━━━━━━━━━━",
    ]
    for s in slots:
        hours = parse_slot_hours(s)
        icon = "✅" if hours >= MIN_HOURS else "⚠️"
        lines.append(f"{icon} {s} ({hours:.1f}h)")
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

    # Sprawdź czy dziś jest sobota
    now = datetime.now(WARSAW_TZ)
    is_saturday = now.isoweekday() == 6

    with sync_playwright() as pw:
        for user in users:
            log.info(f"\n{'='*50}\nUżytkownik: {user['name']}")
            if not should_run(user):
                continue

            # Auto-accept tylko w sobotę, w pozostałe dni tylko powiadamiaj
            accepted_slot, all_slots = check_and_accept_slot(
                user, pw,
                require_saturday=False  # False = przyjmuj każdy slot min. 8h
            )

            if accepted_slot:
                # Slot przyjęty automatycznie!
                msg = format_accepted_message(user, accepted_slot)
                send_telegram(token, user["chat_id"], msg)
                log.info(f"[{user['name']}] 🎉 Przyjęto slot: {accepted_slot}")

            elif all_slots:
                # Są sloty ale żaden nie spełnia kryteriów
                msg = format_found_message(user, all_slots)
                send_telegram(token, user["chat_id"], msg)
                log.info(f"[{user['name']}] Sloty znalezione ale żaden nie pasuje.")

            else:
                log.info(f"[{user['name']}] Brak slotów o {now.strftime('%H:%M')}")

    log.info("Koniec sprawdzania.")


if __name__ == "__main__":
    main()
