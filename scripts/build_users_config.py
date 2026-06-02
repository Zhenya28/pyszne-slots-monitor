#!/usr/bin/env python3
"""
build_users_config.py
Buduje USERS_CONFIG (base64 JSON) z GitHub Secrets i zapisuje do $GITHUB_ENV.
Uruchamiany przez GitHub Actions przed check_slots.py.
"""

import json
import base64
import os

# Czytaj secrets z environment
def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


users = []

# ── Yevhen ────────────────────────────────────────────────────────────────────
yevhen_cookies = env("COOKIES_YEVHEN")
yevhen_chat_id = env("CHAT_ID_YEVHEN")

if yevhen_cookies and yevhen_chat_id:
    users.append({
        "name": "Yevhen Kapush",
        "courier_id": "913698",
        "email": "jeka.kapush@gmail.com",
        "city": "Warszawa",
        "zone": "Center-Mokotow-Srodmiejscie",
        "days": [1, 2, 3, 4, 5, 6, 7],   # Pon-Nd (bot/schedule zmieni przez Gist)
        "hour_from": 7,
        "hour_to": 22,
        "active": True,
        "mute_until": None,
        "chat_id": yevhen_chat_id,
        "cookies_b64": yevhen_cookies,
        "notify_empty": False,
    })
    print(f"✅ Załadowano użytkownika: Yevhen Kapush")

# ── Kolega ────────────────────────────────────────────────────────────────────
kolega_cookies = env("COOKIES_KOLEGA")
kolega_chat_id = env("CHAT_ID_KOLEGA")
kolega_name = env("NAME_KOLEGA")
kolega_courier_id = env("COURIER_ID_KOLEGA")
kolega_email = env("EMAIL_KOLEGA")
kolega_zone = env("ZONE_KOLEGA")

if kolega_cookies and kolega_chat_id and kolega_name:
    users.append({
        "name": kolega_name,
        "courier_id": kolega_courier_id,
        "email": kolega_email,
        "city": "Warszawa",
        "zone": kolega_zone,
        "days": [1, 2, 3, 4, 5, 6, 7],
        "hour_from": 7,
        "hour_to": 22,
        "active": True,
        "mute_until": None,
        "chat_id": kolega_chat_id,
        "cookies_b64": kolega_cookies,
        "notify_empty": False,
    })
    print(f"✅ Załadowano użytkownika: {kolega_name}")

# ── Nadpisz ustawieniami z Gist (dni, godziny, active, mute) ─────────────────
gist_config_b64 = env("GIST_CONFIG_SNAPSHOT")
if gist_config_b64:
    try:
        gist_config = json.loads(base64.b64decode(gist_config_b64).decode())
        for user in users:
            chat_id = user["chat_id"]
            if chat_id in gist_config:
                override = gist_config[chat_id]
                # Nadpisz tylko pola konfiguracyjne (nie dane logowania)
                for field in ["days", "hour_from", "hour_to", "active", "mute_until", "zone", "notify_empty"]:
                    if field in override:
                        user[field] = override[field]
                print(f"✅ Nadpisano ustawienia z Gist dla: {user['name']}")
    except Exception as e:
        print(f"⚠️ Błąd ładowania Gist config: {e} — używam domyślnych.")

if not users:
    print("❌ Brak skonfigurowanych użytkowników!")
    exit(1)

# ── Zapisz do $GITHUB_ENV ─────────────────────────────────────────────────────
users_json = json.dumps(users, ensure_ascii=False)
users_b64 = base64.b64encode(users_json.encode()).decode()

github_env_file = os.environ.get("GITHUB_ENV", "")
if github_env_file:
    with open(github_env_file, "a") as f:
        # Multiline secret — GitHub Actions wymaga specjalnej składni
        f.write(f"USERS_CONFIG={users_b64}\n")
    print(f"✅ USERS_CONFIG zapisany do GITHUB_ENV ({len(users)} użytkowników)")
else:
    # Lokalny test
    print(f"\nUSERS_CONFIG={users_b64[:60]}...")
    print(f"✅ Gotowe ({len(users)} użytkowników)")
