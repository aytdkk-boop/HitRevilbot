# handlers.py
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from config import ADMIN_IDS, COOLDOWN_HOURS, COOLDOWN_MINUTES, KEY_DURATIONS
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, get_stats,
    deactivate_user_keys,
    get_site_id_for_user, reset_activation_for_user,
)
from keyboards import (
    main_menu, close_inline, duration_menu, admin_menu,
    my_keys_menu,
)

router = Router()

# ===== ЧАСОВОЙ ПОЯС =====
LOCAL_TZ = timezone(timedelta(hours=3))


# ===== ФОРМАТИРОВАНИЕ =====

def parse_iso_utc(iso_str: str) -> datetime:
    """Парсит ISO-строку из БД в datetime с таймзоной UTC."""
    if not iso_str:
        raise ValueError("Empty date string")

    s = str(iso_str).strip()

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def fmt_dt(iso_str: str) -> str:
    """Форматирует ISO-дату в 'дд.мм.гггг - чч:мм' в местном поясе."""
    try:
        dt = parse_iso_utc(iso_str)
        dt_local = dt.astimezone(LOCAL_TZ)
        return dt_local.strftime("%d.%m.%Y - %H:%M")
    except Exception as e:
        print(f"⚠️ Ошибка форматирования даты '{iso_str}': {e}")
        return str(iso_str)


def fmt_time_left(seconds: int) -> str:
    """Секунды → '5 мин' или '1 ч 30 мин'."""
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    return " ".join(parts) if parts else "несколько секунд"


def build_start_text() -> str:
    """Текст приветствия при /start."""
    return "\n".join([
        "<b>🤖 Бот активации HITREVIL!</b>",
        "",
        '<b>🔑 Для получения ключа нажмите "🔑 Получить ключ"</b>',
    ])


# ===== /start =====

@router.message(CommandStart())
async def cmd_start(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    is_admin = message.from_user.id in ADMIN_IDS

    await message.answer(
        build_start_text(),
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML",
    )


# ===== ПОЛУЧИТЬ КЛЮЧ =====

@router.message(F.text == "🔑 Получить ключ")
async def get_key_handler(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    existing = get_active_key_for_user(message.from_user.id)

    if existing:
        try:
            expires = parse_iso_utc(existing["expires_at"])
            left = (expires - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            left = 0

        if left > 0:
            text = (
                f"<b>❌ У вас уже есть активный ключ, "
                f"повторное получение ключа доступно через {fmt_time_left(int(left))}</b>"
            )
            await message.answer(
                text,
                reply_markup=close_inline(),
                parse_mode="HTML",
            )
            return

    await message.answer(
        "<b>На сколько вам нужен ключ?</b>",
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
        try:
            expires = parse_iso_utc(existing["expires_at"])
            left = (expires - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            left = 0

        if left > 0:
            try:
                await callback.message.delete()
            except Exception:
                pass
            text = (
                f"<b>❌ У вас уже есть активный ключ, "
                f"повторное получение ключа доступно через {fmt_time_left(int(left))}</b>"
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
    create_key(callback.from_user.id, duration_seconds)

    is_admin = callback.from_user.id in ADMIN_IDS

    # Короткое сообщение об успехе
    await callback.message.answer(
        "<b>✅ Ключ успешно получен!</b>\n\n"
        '<b>Доступен в разделе "✅ Мои ключи"</b>',
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== МОИ КЛЮЧИ =====

@router.message(F.text == "✅ Мои ключи")
async def my_keys_handler(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    user_key = get_active_key_for_user(message.from_user.id)
    site_id = get_site_id_for_user(message.from_user.id)

    if not user_key:
        # Нет активных ключей
        await message.answer(
            "<b>❌ У тебя нет активных ключей!</b>",
            reply_markup=close_inline(),
            parse_mode="HTML",
        )
        return

    # Есть активный ключ — показываем с кнопками
    lines = []
    if site_id:
        lines.append(f"<b>Ваш id HITREVIL -</b> <code>{site_id}</code>")
        lines.append("")

    lines.append(f"<b>✅ Ваш ключ :</b> <code>{user_key['key']}</code>")
    lines.append(f"<b>🕒 Активен до -</b> {fmt_dt(user_key['expires_at'])}")

    text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=my_keys_menu(),
        parse_mode="HTML",
    )


# ===== СБРОС КЛЮЧА (инлайн) =====

@router.callback_query(F.data == "reset_key")
async def reset_key_callback(callback: CallbackQuery):
    init_db()
    create_user(callback.from_user.id, callback.from_user.username or "")

    existing = get_active_key_for_user(callback.from_user.id)

    # Удаляем сообщение с ключом
    try:
        await callback.message.delete()
    except Exception:
        pass

    if existing:
        deactivate_user_keys(callback.from_user.id)
        reset_activation_for_user(callback.from_user.id)

    # Показываем главное меню
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.answer(
        build_start_text(),
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== СТАРЫЙ ОБРАБОТЧИК REPLY-КНОПКИ (на случай, если где-то осталась) =====

@router.message(F.text == "🗑 Сбросить ключ")
async def reset_key_handler(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    existing = get_active_key_for_user(message.from_user.id)

    if existing:
        deactivate_user_keys(message.from_user.id)
        reset_activation_for_user(message.from_user.id)

    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        build_start_text(),
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML",
    )


# ===== ЗАКРЫТЬ ИНЛАЙН-СООБЩЕНИЕ =====

@router.callback_query(F.data == "close_msg")
async def close_msg(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass

    is_admin = callback.from_user.id in ADMIN_IDS

    await callback.message.answer(
        build_start_text(),
        reply_markup=main_menu(is_admin=is_admin),
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