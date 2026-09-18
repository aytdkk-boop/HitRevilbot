# server.py
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import API_SECRET, ALLOWED_ORIGINS
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, activate_key, get_stats,
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


class CreateKeyRequest(BaseModel):
    telegram_id: int
    username: str = ""


class ActivateRequest(BaseModel):
    key: str
    site_id: str | None = None


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