#!/usr/bin/env python3
"""
setup_cookies.py — jednorazowy skrypt do zapisania cookies Google.
Uruchom lokalnie na swoim komputerze. NIE wrzucaj na GitHub.

Użycie:
    pip install playwright
    playwright install chromium
    python setup_cookies.py

Skrypt otworzy przeglądarkę, zaloguj się do Google,
a potem naciśnij Enter — cookies zostaną zapisane.
"""

import json
import base64
import sys
from playwright.sync_api import sync_playwright

EMAIL = input("Podaj swój email Google: ").strip()

print("\n⏳ Otwieram przeglądarkę...")
print("1. Zaloguj się do konta Google")
print("2. Otwórz formularz Pyszne.pl i przejdź przez pierwsze strony")
print("3. Wróć tutaj i naciśnij Enter\n")

FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScb9idqew6_DKUuxw3Qlwi73F5TgsSb3Z6b2QU41egefYmfGw/viewform"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # Widoczna przeglądarka!
    context = browser.new_context()
    page = context.new_page()

    # Otwórz formularz
    page.goto(FORM_URL)
    print(f"✅ Otworzono formularz. Zaloguj się do Google jeśli potrzeba.")
    print("   Naciśnij Enter gdy będziesz gotowy...")
    input()

    # Zapisz cookies
    cookies = context.cookies()
    
    # Filtruj tylko domeny Google
    google_cookies = [
        c for c in cookies
        if "google" in c.get("domain", "").lower()
        or "accounts" in c.get("domain", "").lower()
    ]

    cookies_json = json.dumps(google_cookies, ensure_ascii=False)
    cookies_b64 = base64.b64encode(cookies_json.encode()).decode()

    print(f"\n✅ Zapisano {len(google_cookies)} cookies.")
    
    # Zapisz do pliku
    with open("cookies_output.txt", "w") as f:
        f.write(cookies_b64)
    
    print("\n" + "="*60)
    print("TWOJE COOKIES (base64) — skopiuj to do GitHub Secret:")
    print("="*60)
    print(cookies_b64[:80] + "..." if len(cookies_b64) > 80 else cookies_b64)
    print("="*60)
    print("\n✅ Pełna wartość zapisana w pliku: cookies_output.txt")
    print("   Skopiuj zawartość tego pliku do GitHub Secret 'COOKIES_YEVHEN'")
    print("\n⚠️  NIE wrzucaj cookies_output.txt na GitHub!")

    browser.close()

print("\n✅ Gotowe! Teraz:")
print("1. Idź na GitHub → Settings → Secrets → Actions")
print("2. Dodaj nowy secret: COOKIES_YEVHEN = zawartość cookies_output.txt")
print("3. Usuń plik cookies_output.txt z komputera po skopiowaniu")
