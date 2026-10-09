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

    # Миграция: добавляем site_id и notified, если колонок нет
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

    # Миграция: добавляем banned и can_get_keys в users
    try:
        user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "banned" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
            conn.commit()
        if "can_get_keys" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN can_get_keys INTEGER DEFAULT 1")
            conn.commit()
    except Exception:
        pass

     # Миграция: добавляем camera_enabled
    try:
        user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "camera_enabled" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN camera_enabled INTEGER DEFAULT 1")
            conn.commit()
    except Exception:
        pass

     # Миграция: тумблеры управления пользователем (админские)
     try:
         user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
           if "key_delete_disabled" not in user_cols:
              conn.execute("ALTER TABLE users ADD COLUMN key_delete_disabled INTEGER DEFAULT 0")
              conn.commit()
           if "autosave_disabled" not in user_cols:
              conn.execute("ALTER TABLE users ADD COLUMN autosave_disabled INTEGER DEFAULT 0")
              conn.commit()
.          if "theme_disabled" not in user_cols:
              conn.execute("ALTER TABLE users ADD COLUMN theme_disabled INTEGER DEFAULT 0")
              conn.commit()
      except Exception:
          pass
    
    conn.commit()
    conn.close()


def generate_key() -> str:
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


def user_exists(telegram_id: int) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row is not None


def get_active_key_for_user(telegram_id: int):
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
    key = generate_key()
    expires_at = datetime.utcnow() + timedelta(seconds=duration_seconds)
    expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

    conn = get_conn()
    while conn.execute("SELECT 1 FROM keys WHERE key = ?", (key,)).fetchone():
        key = generate_key()

    conn.execute(
        "INSERT INTO keys (key, telegram_id, expires_at) VALUES (?, ?, ?)",
        (key, telegram_id, expires_at_str),
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


def mark_key_deleted(key: str) -> bool:
    conn = get_conn()
    cursor = conn.execute(
        """UPDATE keys
           SET expires_at = '2000-01-01 00:00:00',
               notified = 1
           WHERE key = ?""",
        (key,),
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def deactivate_user_keys(telegram_id: int) -> int:
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


# ===== АДМИН-ФУНКЦИИ =====

def get_all_users_paginated(page: int, per_page: int = 10):
    offset = (page - 1) * per_page
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM users
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (per_page, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_users_count() -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


def get_user_by_telegram_id(telegram_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_user_banned(telegram_id: int, banned: bool):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET banned = ? WHERE telegram_id = ?",
        (1 if banned else 0, telegram_id),
    )
    conn.commit()
    conn.close()


def set_user_can_get_keys(telegram_id: int, can: bool):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET can_get_keys = ? WHERE telegram_id = ?",
        (1 if can else 0, telegram_id),
    )
    conn.commit()
    conn.close()


def admin_create_key(telegram_id: int, duration_seconds: int) -> dict:
    return create_key(telegram_id, duration_seconds)


def revoke_all_user_keys(telegram_id: int) -> int:
    return deactivate_user_keys(telegram_id)


def delete_key_by_id(key_id: int) -> bool:
    conn = get_conn()
    cursor = conn.execute("DELETE FROM keys WHERE id = ?", (key_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_admin_stats() -> dict:
    """Статистика для админки HITREVIL."""
    conn = get_conn()

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    total_keys = conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0]

    active_keys = conn.execute("""
        SELECT COUNT(*) FROM keys
        WHERE activated = 1
          AND expires_at > CURRENT_TIMESTAMP
    """).fetchone()[0]

    conn.close()

    return {
        "total_users": total_users,
        "total_keys": total_keys,
        "active_keys": active_keys,
        "inactive_keys": total_keys - active_keys,
    }


def is_admin_key(key: str) -> bool:
    """Проверяет, привязан ли ключ к админскому Telegram ID."""
    conn = get_conn()

    row = conn.execute(
        "SELECT telegram_id FROM keys WHERE key = ?",
        (key,),
    ).fetchone()

    conn.close()

    if not row:
        return False

    from config import ADMIN_IDS
    return row["telegram_id"] in ADMIN_IDS


def get_admin_users(limit: int = 20, offset: int = 0) -> dict:
    """
    Список пользователей, у которых есть активированный ключ.
    Показываем только последний активированный ключ каждого юзера.
    Сортировка: новые сверху (по activated_at DESC).
    """
    conn = get_conn()

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Общее число пользователей, у которых есть хотя бы один активированный ключ
    total_with_key = conn.execute("""
        SELECT COUNT(DISTINCT telegram_id)
        FROM keys
        WHERE activated = 1
          AND activated_at IS NOT NULL
    """).fetchone()[0]

    # Берём последний активированный ключ для каждого пользователя
    rows = conn.execute("""
        SELECT
            k.telegram_id,
            k.site_id,
            k.activated_at,
            k.expires_at
        FROM keys k
        INNER JOIN (
            SELECT telegram_id, MAX(activated_at) AS max_activated
            FROM keys
            WHERE activated = 1
              AND activated_at IS NOT NULL
            GROUP BY telegram_id
        ) last
            ON k.telegram_id = last.telegram_id
           AND k.activated_at = last.max_activated
        WHERE k.activated = 1
        ORDER BY k.activated_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()

    conn.close()

    users = []
    for r in rows:
        is_active = False
        try:
            exp = datetime.strptime(r["expires_at"], '%Y-%m-%d %H:%M:%S')
            is_active = exp > datetime.utcnow()
        except Exception:
            pass

        users.append({
            "telegram_id": r["telegram_id"],
            "site_id": r["site_id"] or "",
            "activated_at": r["activated_at"],
            "is_active": is_active,
        })

    return {
        "total_users": total_users,
        "total_with_key": total_with_key,
        "users": users,
    }


def get_users_statuses(telegram_ids: list) -> dict:
    """
    Для переданных telegram_id возвращает {telegram_id: is_active}.
    is_active = у пользователя есть хотя бы один ключ с activated=1 и expires_at > now.
    """
    if not telegram_ids:
        return {}

    conn = get_conn()

    # Формируем безопасные плейсхолдеры
    placeholders = ",".join("?" for _ in telegram_ids)

    rows = conn.execute(f"""
        SELECT telegram_id, MAX(
            CASE WHEN activated = 1 AND expires_at > CURRENT_TIMESTAMP
                 THEN 1 ELSE 0 END
        ) AS is_active
        FROM keys
        WHERE telegram_id IN ({placeholders})
        GROUP BY telegram_id
    """, tuple(telegram_ids)).fetchall()

    conn.close()

    return {int(r["telegram_id"]): bool(r["is_active"]) for r in rows}


def get_user_full(telegram_id: int) -> dict:
    """
    Возвращает полный профиль пользователя для админки.
    site_id возвращается даже если ключа нет — из истории активаций.
    """
    conn = get_conn()

    user = conn.execute(
        "SELECT telegram_id, username, camera_enabled FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    if not user:
        conn.close()
        return {}

    # Последний ключ
    key_row = conn.execute("""
        SELECT key, site_id, expires_at, activated_at, activated
        FROM keys
        WHERE telegram_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (telegram_id,)).fetchone()

    # site_id даже без ключа — из истории
    site_row = conn.execute("""
        SELECT site_id
        FROM keys
        WHERE telegram_id = ?
          AND site_id IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
    """, (telegram_id,)).fetchone()

    conn.close()

    result = {
        "telegram_id": user["telegram_id"],
        "username": user["username"] or "",
        "camera_enabled": bool(user["camera_enabled"] if user["camera_enabled"] is not None else 1),
        "key": None,
        "site_id": site_row["site_id"] if site_row else None,
        "expires_at": None,
        "activated_at": None,
        "is_active": False,
    }

    if key_row:
        result["key"] = key_row["key"]
        if key_row["site_id"]:
            result["site_id"] = key_row["site_id"]
        result["expires_at"] = key_row["expires_at"]
        result["activated_at"] = key_row["activated_at"]

        try:
            exp = datetime.strptime(key_row["expires_at"], '%Y-%m-%d %H:%M:%S')
            is_active = exp > datetime.utcnow() and bool(key_row["activated"])
        except Exception:
            is_active = False

        result["is_active"] = is_active

    return result


def revoke_user_key(telegram_id: int) -> dict:
    """
    Отзывает все ключи пользователя (обычно он один).
    Возвращает ключ, который был отозван (для уведомления в боте).
    """
    conn = get_conn()

    row = conn.execute("""
        SELECT key FROM keys
        WHERE telegram_id = ?
          AND expires_at > CURRENT_TIMESTAMP
        ORDER BY created_at DESC
        LIMIT 1
    """, (telegram_id,)).fetchone()

    revoked_key = row["key"] if row else None

    conn.execute("""
        UPDATE keys
        SET expires_at = '2000-01-01 00:00:00',
            notified = 1,
            activated = 0,
            activated_at = NULL
        WHERE telegram_id = ?
          AND expires_at > CURRENT_TIMESTAMP
    """, (telegram_id,))

    conn.commit()
    conn.close()

    return {"revoked_key": revoked_key}


def grant_user_key(telegram_id: int, duration_seconds: int, site_id: str = None) -> dict:
    """
    Выдаёт пользователю новый ключ.
    Если site_id передан — ключ сразу активируется для этого устройства.
    """
    conn = get_conn()

    # Деактивируем все старые ключи пользователя
    conn.execute("""
        UPDATE keys
        SET expires_at = '2000-01-01 00:00:00',
            activated = 0,
            activated_at = NULL
        WHERE telegram_id = ?
    """, (telegram_id,))

    # Генерируем новый ключ
    key = generate_key()
    expires_at = (datetime.utcnow() + timedelta(seconds=duration_seconds)).strftime('%Y-%m-%d %H:%M:%S')

    if site_id:
        # Сразу активированный ключ, привязанный к устройству
        conn.execute("""
            INSERT INTO keys (key, telegram_id, expires_at, activated, activated_at, site_id)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
        """, (key, telegram_id, expires_at, site_id))
    else:
        # Обычная выдача — юзер должен ввести ключ сам
        conn.execute("""
            INSERT INTO keys (key, telegram_id, expires_at)
            VALUES (?, ?, ?)
        """, (key, telegram_id, expires_at))

    conn.commit()
    conn.close()

    return {
        "key": key,
        "expires_at": expires_at,
        "site_id": site_id,
    }


def find_active_key_by_site_id(site_id: str) -> dict:
    """
    Ищет последний активированный ключ, привязанный к этому site_id.
    Используется для автоматической выдачи ключа на устройстве пользователя.
    """
    if not site_id:
        return {}

    conn = get_conn()
    row = conn.execute("""
        SELECT key, telegram_id, expires_at, activated_at
        FROM keys
        WHERE site_id = ?
          AND activated = 1
          AND expires_at > CURRENT_TIMESTAMP
        ORDER BY activated_at DESC
        LIMIT 1
    """, (site_id,)).fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "key": row["key"],
        "telegram_id": row["telegram_id"],
        "expires_at": row["expires_at"],
        "activated_at": row["activated_at"],
    }


def set_camera_enabled(telegram_id: int, enabled: bool):
    """Включает/выключает камеру для пользователя."""
    conn = get_conn()
    conn.execute(
        "UPDATE users SET camera_enabled = ? WHERE telegram_id = ?",
        (1 if enabled else 0, telegram_id),
    )
    conn.commit()
    conn.close()


def get_camera_enabled(telegram_id: int) -> bool:
    """Возвращает, включена ли камера у пользователя. По умолчанию — True."""
    conn = get_conn()
    row = conn.execute(
        "SELECT camera_enabled FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    conn.close()

    if not row:
        return True
    return bool(row["camera_enabled"] if row["camera_enabled"] is not None else 1)

def get_user_controls(telegram_id: int) -> dict:
    """Возвращает 3 флага блокировок для пользователя."""
    conn = get_conn()
    row = conn.execute("""
        SELECT key_delete_disabled, autosave_disabled, theme_disabled
        FROM users
        WHERE telegram_id = ?
    """, (telegram_id,)).fetchone()
    conn.close()

    if not row:
        return {
            "key_delete_disabled": False,
            "autosave_disabled": False,
            "theme_disabled": False,
        }

    return {
        "key_delete_disabled": bool(row["key_delete_disabled"] or 0),
        "autosave_disabled": bool(row["autosave_disabled"] or 0),
        "theme_disabled": bool(row["theme_disabled"] or 0),
    }


def set_user_control(telegram_id: int, control: str, enabled: bool) -> bool:
    """
    Устанавливает один из флагов блокировки.
    control = 'key_delete' | 'autosave' | 'theme'
    enabled = True → блокировка включена, False → снята.
    """
    column_map = {
        "key_delete": "key_delete_disabled",
        "autosave": "autosave_disabled",
        "theme": "theme_disabled",
    }

    if control not in column_map:
        return False

    column = column_map[control]

    conn = get_conn()
    conn.execute(
        f"UPDATE users SET {column} = ? WHERE telegram_id = ?",
        (1 if enabled else 0, telegram_id),
    )
    conn.commit()
    conn.close()
    return True
