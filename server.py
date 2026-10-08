# server.py
from contextlib import asynccontextmanager

import aiohttp
import base64
import os
import uuid
from datetime import datetime, timedelta
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
    get_admin_users, get_users_statuses,
    get_user_full, revoke_user_key, grant_user_key,
    set_camera_enabled, get_camera_enabled,
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


def _check_admin_key(payload_key: str, payload_site_id: str | None):
    """Проверяет, что ключ существует, не истёк, привязан к этому site_id и админский."""
    key = payload_key.strip()
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

    if not is_admin_key(key):
        raise HTTPException(status_code=403, detail="Admin only")

    if payload_site_id and row.get("site_id") and row["site_id"] != payload_site_id:
        raise HTTPException(status_code=401, detail="Key bound to another device")

    return row


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

class StatusesRequest(BaseModel):
    key: str
    site_id: str | None = None
    telegram_ids: list[int] = []

class UserInfoRequest(BaseModel):
    key: str
    site_id: str | None = None
    telegram_id: int


class UserRevokeRequest(BaseModel):
    key: str
    site_id: str | None = None
    telegram_id: int


class UserGrantRequest(BaseModel):
    key: str
    site_id: str | None = None
    telegram_id: int
    duration: str  # код из KEY_DURATIONS: "2h", "24h", "1m" и т.д.


class UserCameraRequest(BaseModel):
    key: str
    site_id: str | None = None
    telegram_id: int
    enabled: bool


# ===== ЭНДПОИНТЫ =====.

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
    """Возвращает права и статус камеры для текущего ключа."""
    key = payload.key.strip()
    if not key:
        return {"is_admin": False, "camera_enabled": True}

    row = find_key(key)
    if not row:
        return {"is_admin": False, "camera_enabled": True}

    tid = row["telegram_id"]
    return {
        "is_admin": is_admin_key(key),
        "camera_enabled": get_camera_enabled(tid),
    }


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


@app.post("/api/admin/users/statuses")
def api_admin_users_statuses(payload: StatusesRequest):
    """Возвращает текущий статус (активен/не активен) для переданных telegram_id."""
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

    if not is_admin_key(key):
        raise HTTPException(status_code=403, detail="Admin only")

    if payload.site_id and row.get("site_id") and row["site_id"] != payload.site_id:
        raise HTTPException(status_code=401, detail="Key bound to another device")

    # Ограничиваем размер запроса — не больше 100 id за раз
    ids = list(payload.telegram_ids)[:100]

    statuses = get_users_statuses(ids)
    return {"statuses": statuses}


# ===== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ =====

@app.post("/api/admin/user/info")
def api_admin_user_info(payload: UserInfoRequest):
    """Возвращает профиль одного пользователя."""
    _check_admin_key(payload.key, payload.site_id)
    return get_user_full(payload.telegram_id)


@app.post("/api/admin/user/revoke")
def api_admin_user_revoke(payload: UserRevokeRequest):
    """Отзывает ключ пользователя и уведомляет его в боте."""
    _check_admin_key(payload.key, payload.site_id)

    res = revoke_user_key(payload.telegram_id)
    revoked = res.get("revoked_key")

    # Уведомление через бота
    if revoked and BOT_TOKEN:
        try:
            text = (
                f"<b>❗ Ваш ключ {revoked} отозван!</b>\n\n"
                "<b>Доступ к HITREVIL закрыт.</b>"
            )
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": payload.telegram_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": '{"inline_keyboard":[[{"text":"❌ Закрыть","callback_data":"close_msg"}]]}',
            }
            async def _send():
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return await resp.json()
            # Запускаем fire-and-forget через asyncio
            import asyncio
            asyncio.create_task(_send())
        except Exception as e:
            print(f"⚠️ Не удалось уведомить пользователя: {e}")

    return {"ok": True, "revoked_key": revoked}


@app.post("/api/admin/user/grant")
def api_admin_user_grant(payload: UserGrantRequest):
    """Выдаёт пользователю новый ключ и уведомляет его в боте."""
    _check_admin_key(payload.key, payload.site_id)

    duration_code = payload.duration.strip()
    if duration_code not in KEY_DURATIONS:
        raise HTTPException(status_code=400, detail="Invalid duration")

    duration_seconds = KEY_DURATIONS[duration_code]

    res = grant_user_key(payload.telegram_id, duration_seconds)
    new_key = res["key"]
    expires_at = res["expires_at"]

    # Уведомление
    if BOT_TOKEN:
        try:
            # Форматируем дату для бота
            try:
                dt = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
                dt_local = dt + timedelta(hours=3)  # UTC+3
                formatted = dt_local.strftime('%d.%m.%Y - %H:%M')
            except Exception:
                formatted = expires_at

            text = "\n".join([
                "<b>✅ Вам выдан ключ!</b>",
                "",
                f"<b>🔑 Ваш ключ :</b> <code>{new_key}</code>",
                f"<b>🕒 Активен до :</b> <code>{formatted}</code>",
            ])
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": payload.telegram_id,
                "text": text,
                "parse_mode": "HTML",
            }
            async def _send():
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return await resp.json()
            import asyncio
            asyncio.create_task(_send())
        except Exception as e:
            print(f"⚠️ Не удалось уведомить пользователя: {e}")

    return {"ok": True, "key": new_key, "expires_at": expires_at}


@app.post("/api/admin/user/camera")
def api_admin_user_camera(payload: UserCameraRequest):
    """Включает/выключает камеру для пользователя."""
    _check_admin_key(payload.key, payload.site_id)

    set_camera_enabled(payload.telegram_id, bool(payload.enabled))
    return {"ok": True, "camera_enabled": bool(payload.enabled)}
