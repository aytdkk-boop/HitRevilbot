# config.py
from os import getenv

# ===== TELEGRAM =====
BOT_TOKEN = getenv("BOT_TOKEN", "8964898677:AAFI0kY89AQhgrpXNDPbkQYeVHtgujYS8_g")

# ID администраторов (узнать у @userinfobot)
ADMIN_IDS = [int(x) for x in getenv("ADMIN_IDS", "7317419505").split(",")]

# ===== API =====
API_SECRET = getenv("API_SECRET", "change-me-to-random-string")
API_HOST = getenv("API_HOST", "0.0.0.0")
API_PORT = int(getenv("PORT", getenv("API_PORT", "3000")))
API_URL = getenv("API_URL", f"http://127.0.0.1:{API_PORT}")

# Домены, которым разрешено обращаться к API
ALLOWED_ORIGINS = [
    "https://aytdkk-boop.github.io",
    "http://localhost:8000",
]

# ===== ЛОГИКА КЛЮЧЕЙ =====
KEY_LENGTH = 16
COOLDOWN_HOURS = 1
COOLDOWN_MINUTES = 30

KEY_DURATIONS = {
    "test": 5 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
    "48h": 48 * 60 * 60,
    "1m": 30 * 24 * 60 * 60,
}
