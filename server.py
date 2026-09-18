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


class ActivateRequest(BaseModel):
    key: str


@app.on_event("startup")
def on_startup():
    init_db()
    print("✅ База данных инициализирована")


@app.get("/")
def root():
    return {"status": "ok", "service": "HITREVIL API"}


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
    return activate_key(key)


@app.get("/api/stats")
def api_stats(authorization: str = Header(...)):
    check_secret(authorization)
    return get_stats()