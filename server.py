# server.py
from contextlib import asynccontextmanager

import aiohttp
import base64
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    API_SECRET, ALLOWED_ORIGINS, BOT_TOKEN,
    PUBLIC_BASE_URL, KEY_DURATIONS,
)
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, activate_key, get_stats,
    find_key, mark_key_deleted, get_admin_stats, is_admin_key,
    get_admin_users,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    init_db()
    print("✅ База данных инициализирована")
    yield
    # shutdown (если понадобится — добавьте тут очистку ресурсов)


app = FastAPI(title="HITREVIL API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ===== ПАПКА ДЛЯ ЗАГРУЖЕННЫХ ФОТО =====
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def check_secret(auth: str):
    if auth != f"Bearer {API_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ===== МОДЕЛИ =====

class CreateKeyRequest(BaseModel):
    telegram_id: int
    username: str = ""


class ActivateRequest(BaseModel):
    key: str
    site_id: str | None = None


class CheckRequest(BaseModel):
    key: str
    site_id: str | None = None


class NotifyDeletedRequest(BaseModel):
    key: str


class UploadRequest(BaseModel):
    dataURL: str

class AdminStatsRequest(BaseModel):
    key: str
    site_id: str | None = None

class MeRequest(BaseModel):
    key: str

class AdminUsersRequest(BaseModel):
    key: str
    site_id: str | None = None
    limit: int = 20
    offset: int = 0


# ===== ЭНДПОИНТЫ =====

@app.get("/")
def root():
    return {"status": "ok", "service": "HITREVIL API"}


@app.post("/api/keys")
def api_create_key(payload: CreateKeyRequest, authorization: str = Header(...)):
    check_secret(authorization)

    create_user(payload.telegram_id, payload.username)

    existing = get_active_key_for_user(payload.telegram_id)
    if existing:
        return {
            "key": existing["key"],
            "created_at": existing["created_at"],
            "expires_at": existing["expires_at"],
            "existing": True,
        }

    duration = KEY_DURATIONS.get("24h", 24 * 60 * 60)
    new_key = create_key(payload.telegram_id, duration)
    return {
        "key": new_key["key"],
        "created_at": new_key["created_at"],
        "expires_at": new_key["expires_at"],
        "existing": False,
    }


@app.get("/api/users/{telegram_id}/key")
def api_get_user_key(telegram_id: int, authorization: str = Header(...)):
    check_secret(authorization)

    key = get_active_key_for_user(telegram_id)
    if not key:
        return {"key": None, "is_active": False}

    return {
        "key": key["key"],
        "created_at": key["created_at"],
        "expires_at": key["expires_at"],
        "activated": bool(key["activated"]),
        "is_active": True,
    }


@app.post("/api/activate")
def api_activate(payload: ActivateRequest):
    """Активация ключа на сайте. Используется при первой активации."""
    key = payload.key.strip()
    if not key:
        return {"valid": False, "reason": "empty"}
    return activate_key(key, site_id=payload.site_id)


@app.post("/api/check")
def api_check(payload: CheckRequest):
    """
    Проверка ключа БЕЗ активации. Используется для периодической
    проверки (каждые 5 секунд). НЕ меняет данные в БД.
    """
    key = payload.key.strip()
    if not key:
        return {"valid": False, "reason": "empty"}

    row = find_key(key)
    if not row:
        return {"valid": False, "reason": "not_found"}

    try:
        expires_at = datetime.strptime(row["expires_at"], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        expires_at = datetime.fromisoformat(row["expires_at"].replace('Z', ''))

    if expires_at < datetime.utcnow():
        return {"valid": False, "reason": "expired"}

    if row["activated"]:
        return {
            "valid": False,
            "reason": "already_used",
            "site_id": row.get("site_id"),
            "expires_at": row["expires_at"],
        }

    return {
        "valid": True,
        "expires_at": row["expires_at"],
        "site_id": row.get("site_id"),
    }


@app.get("/api/stats")
def api_stats(authorization: str = Header(...)):
    check_secret(authorization)
    return get_stats()


@app.post("/api/notify_deleted")
async def api_notify_deleted(payload: NotifyDeletedRequest):
    """Уведомление об удалении ключа на сайте."""
    if not BOT_TOKEN:
        return {"ok": False, "reason": "no_bot_token"}

    key = payload.key.strip()
    if not key:
        return {"ok": False, "reason": "empty_key"}

    row = find_key(key)
    if not row:
        return {"ok": False, "reason": "key_not_found"}

    telegram_id = row["telegram_id"]
    if not telegram_id:
        return {"ok": False, "reason": "no_telegram_id"}

    updated = mark_key_deleted(key)
    print(f"🔒 Ключ {key} помечен как удалённый (updated={updated})")

    text = (
        "<b>❗Вы удалили ключ, для использования HITREVIL, "
        "необходимо получить ключ!</b>"
    )

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": telegram_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": '{"inline_keyboard":[[{"text":"❌ Закрыть","callback_data":"close_msg"}]]}'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                print(f"📤 Уведомление об удалении: chat_id={telegram_id}, ok={result.get('ok')}")
                return {"ok": result.get("ok", False)}
    except Exception as e:
        print(f"⚠️ Ошибка отправки уведомления: {e}")
        return {"ok": False, "reason": str(e)}


@app.post("/api/upload")
async def api_upload(payload: UploadRequest):
    """Принимает base64-картинку, сохраняет в uploads/ и возвращает публичный URL."""
    data_url = payload.dataURL
    if not data_url or not data_url.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Invalid image format")

    try:
        header, b64data = data_url.split(",", 1)

        ext = "jpg"
        if "image/png" in header:
            ext = "png"
        elif "image/webp" in header:
            ext = "webp"
        elif "image/jpeg" in header or "image/jpg" in header:
            ext = "jpg"

        raw = base64.b64decode(b64data)
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(raw)

        # Публичный абсолютный URL — обязателен для median.share.downloadImage
        public_url = f"{PUBLIC_BASE_URL.rstrip('/')}/uploads/{filename}"
        print(f"📷 Фото загружено: {public_url}")
        return {"url": public_url}

    except Exception as e:
        print(f"⚠️ Ошибка загрузки фото: {e}")
        raise HTTPException(status_code=500, detail="Upload failed")


@app.post("/api/admin/stats")
def api_admin_stats(payload: AdminStatsRequest):
    """Статистика для админки HITREVIL. Проверяется по ключу активации."""
    key = payload.key.strip()
    if not key:
        raise HTTPException(status_code=401, detail="No key")

    row = find_key(key)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid key")

    try:
        expires_at = datetime.strptime(row["expires_at"], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        expires_at = datetime.fromisoformat(row["expires_at"].replace('Z', ''))

    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Key expired")

    if payload.site_id and row.get("site_id") and row["site_id"] != payload.site_id:
        raise HTTPException(status_code=401, detail="Key bound to another device")

    return get_admin_stats()


@app.post("/api/me")
def api_me(payload: MeRequest):
    """Возвращает, является ли ключ админским."""
    key = payload.key.strip()
    if not key:
        return {"is_admin": False}

    return {"is_admin": is_admin_key(key)}


@app.post("/api/admin/users")
def api_admin_users(payload: AdminUsersRequest):
    """Список пользователей с активированными ключами. Только для админов."""
    key = payload.key.strip()
    if not key:
        raise HTTPException(status_code=401, detail="No key")

    # Проверяем, что ключ вообще существует и не истёк
    row = find_key(key)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid key")

    try:
        expires_at = datetime.strptime(row["expires_at"], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        expires_at = datetime.fromisoformat(row["expires_at"].replace('Z', ''))

    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Key expired")

    # Проверяем, что ключ админский
    if not is_admin_key(key):
        raise HTTPException(status_code=403, detail="Admin only")

    # Привязка к устройству
    if payload.site_id and row.get("site_id") and row["site_id"] != payload.site_id:
        raise HTTPException(status_code=401, detail="Key bound to another device")

    # Ограничиваем разумно, чтобы не выгрузить всю БД случайно
    limit = max(1, min(int(payload.limit), 100))
    offset = max(0, int(payload.offset))

    return get_admin_users(limit=limit, offset=offset)
