# 🍕 Pyszne Slot Monitor Bot

Bot Telegram który monitoruje formularz wymiany slotów Pyszne.pl i powiadamia gdy pojawią się dostępne zmiany.

## Jak to działa

```
GitHub Actions (co 10 min, darmowe dla public repo)
    ↓
Python + Playwright (otwiera formularz, loguje się, sprawdza sloty)
    ↓
Telegram Bot API
    ↓
Powiadomienie na Twoim telefonie 📱
```

---

## 🚀 Instalacja krok po kroku

### Krok 1 — Fork repozytorium

1. Wejdź na `https://github.com/Zhenya28/pyszne-slot-monitor`
2. Kliknij **Fork** (prawy górny róg)
3. Repozytorium musi być **publiczne** (GitHub Actions darmowe tylko dla public)

---

### Krok 2 — Zapisz cookies Google (jednorazowo, na swoim komputerze)

```bash
# Zainstaluj zależności
pip install playwright
playwright install chromium

# Uruchom skrypt
python scripts/setup_cookies.py
```

Skrypt otworzy przeglądarkę. Zaloguj się do Google, wejdź na formularz Pyszne.pl, wróć i naciśnij Enter.

Skrypt zapisze plik `cookies_output.txt` — **skopiuj jego zawartość** (długi ciąg znaków).

> ⚠️ NIE wrzucaj `cookies_output.txt` na GitHub! Plik jest w .gitignore.

---

### Krok 3 — Dodaj GitHub Secrets

Wejdź: `GitHub repo → Settings → Secrets and variables → Actions → New repository secret`

| Secret Name | Wartość |
|-------------|---------|
| `TELEGRAM_TOKEN` | `8836649620:AAENAffm1NFdPZDp07x4UnR_1U3H_2q_99Y` |
| `CHAT_ID_YEVHEN` | `5919940612` |
| `COOKIES_YEVHEN` | zawartość `cookies_output.txt` |

**Dla kolegi (gdy będzie gotowy):**

| Secret Name | Wartość |
|-------------|---------|
| `CHAT_ID_KOLEGA` | jego Telegram Chat ID |
| `COOKIES_KOLEGA` | jego cookies (niech uruchomi setup_cookies.py) |
| `NAME_KOLEGA` | jego imię i nazwisko |
| `COURIER_ID_KOLEGA` | jego ID kuriera |
| `EMAIL_KOLEGA` | jego email Google |
| `ZONE_KOLEGA` | jego strefa (np. `Praga-Poludnie`) |

---

### Krok 4 — Włącz GitHub Actions

1. Wejdź w repo → zakładka **Actions**
2. Kliknij **"I understand my workflows, go ahead and enable them"**
3. Kliknij na workflow **"Pyszne Slot Monitor"**
4. Kliknij **"Run workflow"** → **"Run workflow"** (test ręczny)
5. Sprawdź czy nie ma błędów (zielony ✅)

---

### Krok 5 — Uruchom Telegram Bota (opcjonalnie)

Bot działa lokalnie lub na darmowym hostingu (Railway, Fly.io).

```bash
export TELEGRAM_TOKEN="8836649620:AAENAffm1NFdPZDp07x4UnR_1U3H_2q_99Y"
export GIST_ID="twój_gist_id"
export GITHUB_TOKEN="twój_github_token"
pip install python-telegram-bot pytz requests
python bot/bot.py
```

> Bez bota też działa! GitHub Actions wysyła powiadomienia automatycznie.
> Bot dodaje tylko komendy /pause, /schedule itp.

---

## 📱 Komendy Telegram Bota

| Komenda | Opis |
|---------|------|
| `/start` | Rejestracja / powitanie |
| `/status` | Pokaż swój profil i ustawienia |
| `/schedule` | Zmień dni i godziny monitorowania |
| `/zone` | Zmień strefę |
| `/check` | Sprawdź sloty TERAZ |
| `/pause` | Zatrzymaj powiadomienia |
| `/resume` | Wznów powiadomienia |
| `/mute 2` | Wycisz na 2 godziny |
| `/help` | Lista komend |

---

## 🔧 Konfiguracja harmonogramu w GitHub Actions

Plik `.github/workflows/check_slots.yml`:

```yaml
- cron: '*/10 5-21 * * *'
```

- `*/10` = co 10 minut
- `5-21` = godziny UTC (= 7-23 czasu warszawskiego zimą)
- `* * *` = każdy dzień, każdy miesiąc, każdy dzień tygodnia

Zmień `5-21` jeśli chcesz inne godziny (pamiętaj że GitHub używa UTC).

---

## ❓ FAQ

**Dlaczego używamy publicznego repo?**
GitHub Actions jest darmowe bez limitu dla publicznych repozytoriów. Prywatne mają limit 2000 min/miesiąc.

**Czy moje cookies są bezpieczne?**
Tak — cookies zapisane są jako **GitHub Secrets** (zaszyfrowane, niewidoczne nawet dla Ciebie po zapisaniu). Nigdy nie pojawiają się w logach.

**Co jeśli Actions się wyłączy po 60 dniach?**
Workflow `keepalive.yml` automatycznie zapobiega temu co 45 dni.

**Opóźnienia w powiadomieniach?**
GitHub Actions może opóźnić uruchomienie o 5-30 minut podczas dużego ruchu. To normalne — dla slotów kurierskich jest akceptowalne.

**Jak dodać kolejnego użytkownika?**
Dodaj jego secrets do repo (CHAT_ID_KOLEGA2, COOKIES_KOLEGA2 itd.) i dodaj go w `build_users_config.py`.

---

## 📁 Struktura projektu

```
pyszne-slot-monitor/
├── .github/
│   └── workflows/
│       ├── check_slots.yml      # Główny workflow (co 10 min)
│       └── keepalive.yml        # Zapobiega wyłączeniu po 60 dniach
├── bot/
│   └── bot.py                   # Telegram Bot (komendy /start, /pause itp.)
├── scripts/
│   ├── check_slots.py           # Scraper formularza Pyszne.pl
│   ├── build_users_config.py    # Buduje config z GitHub Secrets
│   └── setup_cookies.py         # Jednorazowy — zapisuje cookies Google
├── requirements.txt
├── .gitignore
└── README.md
```
