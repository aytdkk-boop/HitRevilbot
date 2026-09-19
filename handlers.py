# handlers.py
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.markdown import bold

from config import ADMIN_IDS, COOLDOWN_HOURS, COOLDOWN_MINUTES, KEY_DURATIONS
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, get_stats,
    deactivate_user_keys,
    get_site_id_for_user, reset_activation_for_user,
)
from keyboards import main_menu, close_inline, duration_menu, admin_menu

router = Router()

# ===== ЧАСОВОЙ ПОЯС =====
# Сервер Bothost работает в UTC. Ключи создаются в UTC.
# Здесь мы переводим UTC в местное время для отображения.
# По умолчанию — Москва (UTC+3). Поменяйте на своё смещение.
LOCAL_TZ = timezone(timedelta(hours=3))


# ===== ФОРМАТИРОВАНИЕ ДАТЫ =====

def parse_iso_utc(iso_str: str) -> datetime:
    """
    Парсит ISO-строку из БД и возвращает datetime с таймзоной UTC.
    Учитывает разные форматы: с 'Z', с '+00:00', без таймзоны.
    """
    if not iso_str:
        raise ValueError("Empty date string")

    s = str(iso_str).strip()

    # Пробуем стандартный парсер
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        # Если не получилось — пробуем заменить пробел на T
        dt = datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))

    # Если таймзона не указана — считаем, что это UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def fmt_dt(iso_str: str) -> str:
    """
    Форматирует ISO-дату в 'дд.мм.гггг - чч:мм' в местном часовом поясе.
    """
    try:
        dt = parse_iso_utc(iso_str)
        dt_local = dt.astimezone(LOCAL_TZ)
        return dt_local.strftime("%d.%m.%Y - %H:%M")
    except Exception as e:
        print(f"⚠️ Ошибка форматирования даты '{iso_str}': {e}")
        return str(iso_str)


# ===== ТЕКСТ ГЛАВНОГО МЕНЮ =====

def build_menu_text(user_key: dict | None = None, site_id: str | None = None) -> str:
    """Собирает текст главного меню с жирным шрифтом и code-блоками."""
    lines = [
        bold("🤖 Бот активации HITREVIL!"),
        "",
        bold('🔑 Для получения ключа нажмите "🔑 Получить ключ"'),
        "",
    ]

    if site_id:
        lines.append(bold("Ваш id в HITREVIL :") + f"  <code>{site_id}</code>")
        lines.append("")

    if user_key and user_key.get("key"):
        lines.append(bold("✅ Ваш ключ :") + f"  <code>{user_key['key']}</code>")
        lines.append(bold("🕒 Активен до :") + f"  {fmt_dt(user_key['expires_at'])}")

    return "\n".join(lines)


def fmt_time_left(seconds: int) -> str:
    """Секунды → '1ч 30 мин'."""
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    return " ".join(parts) if parts else "несколько секунд"


# ===== /start =====

@router.message(CommandStart())
async def cmd_start(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    user_key = get_active_key_for_user(message.from_user.id)
    site_id = get_site_id_for_user(message.from_user.id)
    is_admin = message.from_user.id in ADMIN_IDS
    has_key = bool(user_key)

    text = build_menu_text(user_key, site_id)

    await message.answer(
        text,
        reply_markup=main_menu(is_admin=is_admin, has_key=has_key),
        parse_mode="HTML",
    )


# ===== ПОЛУЧИТЬ КЛЮЧ =====

@router.message(F.text == "🔑 Получить ключ")
async def get_key_handler(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    existing = get_active_key_for_user(message.from_user.id)

    if existing:
        cooldown_seconds = COOLDOWN_HOURS * 3600 + COOLDOWN_MINUTES * 60
        try:
            created = parse_iso_utc(existing["created_at"])
        except Exception:
            created = datetime.now(timezone.utc)

        next_time = created + timedelta(seconds=cooldown_seconds)
        left = (next_time - datetime.now(timezone.utc)).total_seconds()

        if left > 0:
            text = bold(
                f"❌ У вас уже есть активный ключ, "
                f"повторное получение ключа доступно через {fmt_time_left(int(left))}!"
            )
            await message.answer(
                text,
                reply_markup=close_inline(),
                parse_mode="HTML",
            )
            return

    await message.answer(
        bold("На сколько вам нужен ключ?"),
        reply_markup=duration_menu(),
        parse_mode="HTML",
    )


# ===== ВЫБОР ДЛИТЕЛЬНОСТИ =====

@router.callback_query(F.data.startswith("dur:"))
async def choose_duration(callback: CallbackQuery):
    duration_code = callback.data.split(":", 1)[1]

    if duration_code not in KEY_DURATIONS:
        await callback.answer("Неизвестный срок", show_alert=True)
        return

    duration_seconds = KEY_DURATIONS[duration_code]

    # Повторная проверка активного ключа
    existing = get_active_key_for_user(callback.from_user.id)
    if existing:
        cooldown_seconds = COOLDOWN_HOURS * 3600 + COOLDOWN_MINUTES * 60
        try:
            created = parse_iso_utc(existing["created_at"])
        except Exception:
            created = datetime.now(timezone.utc)

        next_time = created + timedelta(seconds=cooldown_seconds)
        left = (next_time - datetime.now(timezone.utc)).total_seconds()

        if left > 0:
            try:
                await callback.message.delete()
            except Exception:
                pass
            text = bold(
                f"❌ У вас уже есть активный ключ, "
                f"повторное получение ключа доступно через {fmt_time_left(int(left))}!"
            )
            await callback.message.answer(
                text,
                reply_markup=close_inline(),
                parse_mode="HTML",
            )
            await callback.answer()
            return

    # Удаляем сообщение с меню сроков
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Создаём ключ
    new_key = create_key(callback.from_user.id, duration_seconds)

    # Получаем site_id (если пользователь уже активировал что-то на сайте)
    site_id = get_site_id_for_user(callback.from_user.id)

    # Формируем сообщение через общий шаблон
    text = build_menu_text(new_key, site_id)

    await callback.message.answer(
        text,
        reply_markup=main_menu(
            is_admin=callback.from_user.id in ADMIN_IDS,
            has_key=True,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== СБРОС КЛЮЧА =====

@router.message(F.text == "🗑 Сбросить ключ")
async def reset_key_handler(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    existing = get_active_key_for_user(message.from_user.id)

    if not existing:
        site_id = get_site_id_for_user(message.from_user.id)
        text = build_menu_text(None, site_id)
        is_admin = message.from_user.id in ADMIN_IDS
        await message.answer(
            text,
            reply_markup=main_menu(is_admin=is_admin, has_key=False),
            parse_mode="HTML",
        )
        return

    count = deactivate_user_keys(message.from_user.id)
    reset_activation_for_user(message.from_user.id)

    is_admin = message.from_user.id in ADMIN_IDS
    site_id = get_site_id_for_user(message.from_user.id)

    text = build_menu_text(None, site_id)
    await message.answer(
        text,
        reply_markup=main_menu(is_admin=is_admin, has_key=False),
        parse_mode="HTML",
    )

    if count > 0:
        await message.answer(
            bold("🗑 Ключ сброшен. Теперь вы можете получить новый ключ."),
            parse_mode="HTML",
        )


# ===== ЗАКРЫТЬ ИНЛАЙН-СООБЩЕНИЕ =====

@router.callback_query(F.data == "close_msg")
async def close_msg(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass

    user_key = get_active_key_for_user(callback.from_user.id)
    site_id = get_site_id_for_user(callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS
    has_key = bool(user_key)
    text = build_menu_text(user_key, site_id)

    await callback.message.answer(
        text,
        reply_markup=main_menu(is_admin=is_admin, has_key=has_key),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== АДМИНКА =====

@router.message(F.text == "⚙️ Админка")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "⚙️ <b>Админ-панель</b>",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    stats = get_stats()
    text = "\n".join([
        "<b>📊 Статистика</b>",
        "",
        f"👥 Пользователей: <b>{stats['total_users']}</b>",
        f"🔑 Всего ключей: <b>{stats['total_keys']}</b>",
        f"✅ Активных: <b>{stats['active_keys']}</b>",
        f"📸 Активировано на сайте: <b>{stats['activated_keys']}</b>",
    ])
    await callback.message.edit_text(
        text,
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()