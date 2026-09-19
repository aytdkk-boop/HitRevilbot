# server.py
import aiohttp
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import API_SECRET, ALLOWED_ORIGINS, BOT_TOKEN
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, activate_key, get_stats,
    find_key, mark_key_deleted,
)

app = FastAPI(title="HITREVIL API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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


class NotifyDeletedRequest(BaseModel):
    key: str


# ===== ЭНДПОИНТЫ =====

@app.on_event("startup")
def on_startup():
    init_db()
    print("✅ База данных инициализирована")


@app.get("/")
def root():
    return {"status": "ok", "service": "HITREVIL API"}


@app.post("/api/keys")
def api_create_key(payload: CreateKeyRequest, authorization: str = Header(...)):
    """Создаёт ключ для бота."""
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

    new_key = create_key(payload.telegram_id)
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
    key = payload.key.strip()
    if not key:
        return {"valid": False, "reason": "empty"}
    return activate_key(key, site_id=payload.site_id)


@app.get("/api/stats")
def api_stats(authorization: str = Header(...)):
    check_secret(authorization)
    return get_stats()


@app.post("/api/notify_deleted")
async def api_notify_deleted(payload: NotifyDeletedRequest):
    """
    Отправляет уведомление, что пользователь удалил ключ.
    Также помечает ключ как notified=1, чтобы фоновая задача
    не отправила второе сообщение об истечении.
    """
    if not BOT_TOKEN:
        print("⚠️ notify_deleted: BOT_TOKEN не задан")
        return {"ok": False, "reason": "no_bot_token"}

    key = payload.key.strip()
    if not key:
        return {"ok": False, "reason": "empty_key"}

    # Ищем ключ в БД
    row = find_key(key)
    if not row:
        print(f"⚠️ notify_deleted: ключ {key} не найден в БД")
        return {"ok": False, "reason": "key_not_found"}

    telegram_id = row["telegram_id"]
    if not telegram_id:
        return {"ok": False, "reason": "no_telegram_id"}

    # ⚠️ ВАЖНО: сначала помечаем ключ как удалённый,
    # чтобы фоновая задача точно не нашла его.
    updated = mark_key_deleted(key)
    print(f"🔒 Ключ {key} помечен как удалённый (updated={updated})")

    # Отправляем уведомление об удалении
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