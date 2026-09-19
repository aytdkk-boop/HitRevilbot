# database.py
import sqlite3
import secrets
import string
from datetime import datetime, timedelta
from pathlib import Path

from config import KEY_LENGTH

DB_PATH = Path(__file__).parent / "hitrevil.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id   INTEGER PRIMARY KEY,
            username      TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS keys (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            key           TEXT UNIQUE NOT NULL,
            telegram_id   INTEGER NOT NULL,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at    DATETIME NOT NULL,
            activated     INTEGER DEFAULT 0,
            activated_at  DATETIME,
            notified      INTEGER DEFAULT 0,
            site_id       TEXT,
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
        );

        CREATE INDEX IF NOT EXISTS idx_keys_key ON keys(key);
        CREATE INDEX IF NOT EXISTS idx_keys_telegram ON keys(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_keys_site_id ON keys(site_id);
    """)

    # Миграция: добавляем site_id, если колонки ещё нет
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(keys)").fetchall()]
        if "site_id" not in cols:
            conn.execute("ALTER TABLE keys ADD COLUMN site_id TEXT")
            conn.commit()
        if "notified" not in cols:
            conn.execute("ALTER TABLE keys ADD COLUMN notified INTEGER DEFAULT 0")
            conn.commit()
    except Exception:
        pass

    conn.commit()
    conn.close()


def generate_key() -> str:
    """16-символьный ключ: A-Z, a-z, 0-9."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(KEY_LENGTH))


def create_user(telegram_id: int, username: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
        (telegram_id, username),
    )
    conn.execute(
        "UPDATE users SET username = ? WHERE telegram_id = ?",
        (username, telegram_id),
    )
    conn.commit()
    conn.close()


def get_active_key_for_user(telegram_id: int):
    """Возвращает последний активный (не истёкший) ключ пользователя."""
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM keys
           WHERE telegram_id = ?
             AND expires_at > CURRENT_TIMESTAMP
           ORDER BY created_at DESC
           LIMIT 1""",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_last_key_for_user(telegram_id: int):
    """Возвращает последний ключ пользователя (даже если истёк)."""
    conn = get_conn()
    row = conn.execute(
        """SELECT * FROM keys
           WHERE telegram_id = ?
           ORDER BY created_at DESC
           LIMIT 1""",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_key(telegram_id: int, duration_seconds: int) -> dict:
    """Создаёт ключ с указанным сроком жизни."""
    key = generate_key()
    expires_at = datetime.utcnow() + timedelta(seconds=duration_seconds)

    conn = get_conn()
    while conn.execute("SELECT 1 FROM keys WHERE key = ?", (key,)).fetchone():
        key = generate_key()

    conn.execute(
        "INSERT INTO keys (key, telegram_id, expires_at) VALUES (?, ?, ?)",
        (key, telegram_id, expires_at.isoformat()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()
    conn.close()
    return dict(row)


def find_key(key: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM keys WHERE key = ?", (key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def activate_key(key: str, site_id: str | None = None) -> dict:
    """
    Проверяет и активирует ключ на сайте.
    Если передан site_id — сохраняет его в БД.
    """
    row = find_key(key)
    if not row:
        return {"valid": False, "reason": "not_found"}

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at < datetime.utcnow():
        return {"valid": False, "reason": "expired"}

    if row["activated"]:
        return {
            "valid": False,
            "reason": "already_used",
            "site_id": row.get("site_id"),
        }

    conn = get_conn()
    if site_id:
        conn.execute(
            """UPDATE keys
               SET activated = 1,
                   activated_at = CURRENT_TIMESTAMP,
                   site_id = ?
               WHERE key = ?""",
            (site_id, key),
        )
    else:
        conn.execute(
            """UPDATE keys
               SET activated = 1,
                   activated_at = CURRENT_TIMESTAMP
               WHERE key = ?""",
            (key,),
        )
    conn.commit()
    conn.close()

    return {
        "valid": True,
        "expires_at": row["expires_at"],
        "site_id": site_id or row.get("site_id"),
    }


def get_keys_expiring_soon(seconds: int = 120):
    """
    Возвращает ключи, которые истекут в ближайшие `seconds` секунд
    и по которым ещё не отправлено уведомление.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM keys
           WHERE expires_at > CURRENT_TIMESTAMP
             AND expires_at <= datetime(CURRENT_TIMESTAMP, '+' || ? || ' seconds')
             AND notified = 0
           ORDER BY expires_at ASC""",
        (seconds,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_expired_keys_not_notified():
    """Возвращает ключи, которые уже истекли, но уведомление не отправлено."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM keys
           WHERE expires_at <= CURRENT_TIMESTAMP
             AND notified = 0
           ORDER BY expires_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_key_notified(key_id: int):
    conn = get_conn()
    conn.execute("UPDATE keys SET notified = 1 WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()


def deactivate_user_keys(telegram_id: int) -> int:
    """
    Сбрасывает все активные ключи пользователя.
    Возвращает количество сброшенных ключей.
    """
    conn = get_conn()
    count_row = conn.execute(
        """SELECT COUNT(*) FROM keys
           WHERE telegram_id = ?
             AND expires_at > CURRENT_TIMESTAMP""",
        (telegram_id,),
    ).fetchone()
    count = count_row[0] if count_row else 0

    if count > 0:
        conn.execute(
            """UPDATE keys
               SET expires_at = '2000-01-01 00:00:00',
                   notified = 1
               WHERE telegram_id = ?
                 AND expires_at > CURRENT_TIMESTAMP""",
            (telegram_id,),
        )
        conn.commit()

    conn.close()
    return count


def get_site_id_for_user(telegram_id: int):
    """Возвращает site_id из последнего активированного ключа пользователя."""
    conn = get_conn()
    row = conn.execute(
        """SELECT site_id FROM keys
           WHERE telegram_id = ?
             AND activated = 1
             AND site_id IS NOT NULL
           ORDER BY activated_at DESC
           LIMIT 1""",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row["site_id"] if row and row["site_id"] else None


def reset_activation_for_user(telegram_id: int) -> int:
    """
    Сбрасывает флаг активации у всех ключей пользователя.
    site_id при этом НЕ удаляется — он остаётся навсегда.
    """
    conn = get_conn()
    cursor = conn.execute(
        """UPDATE keys
           SET activated = 0,
               activated_at = NULL
           WHERE telegram_id = ?
             AND activated = 1""",
        (telegram_id,),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def get_stats() -> dict:
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_keys = conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
    active_keys = conn.execute(
        "SELECT COUNT(*) FROM keys WHERE expires_at > CURRENT_TIMESTAMP"
    ).fetchone()[0]
    activated_keys = conn.execute(
        "SELECT COUNT(*) FROM keys WHERE activated = 1"
    ).fetchone()[0]
    conn.close()
    return {
        "total_users": total_users,
        "total_keys": total_keys,
        "active_keys": active_keys,
        "activated_keys": activated_keys,
    }