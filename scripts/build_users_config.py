#!/usr/bin/env python3
"""
build_users_config.py
Buduje USERS_CONFIG (base64 JSON) z GitHub Secrets i zapisuje do $GITHUB_ENV.
"""

import json
import base64
import os


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
        "zone": "Center-Mokotow-Srodmiescie",
        "days": [1, 2, 3, 4, 5, 6, 7],
        "hour_from": 7,
        "hour_to": 22,
        "active": True,
        "mute_until": None,
        "chat_id": yevhen_chat_id,
        "cookies_b64": yevhen_cookies,
        "notify_empty": False,
    })
    print("✅ Yevhen Kapush załadowany.")

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
    print(f"✅ {kolega_name} załadowany.")

if not users:
    print("❌ Brak użytkowników!")
    exit(1)

# ── Zapisz do $GITHUB_ENV ─────────────────────────────────────────────────────
users_b64 = base64.b64encode(json.dumps(users, ensure_ascii=False).encode()).decode()

github_env = os.environ.get("GITHUB_ENV", "")
if github_env:
    with open(github_env, "a") as f:
        f.write(f"USERS_CONFIG={users_b64}\n")
    print(f"✅ USERS_CONFIG zapisany ({len(users)} użytkowników).")
else:
    print(f"USERS_CONFIG={users_b64[:60]}...")