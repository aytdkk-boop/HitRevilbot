# handlers.py
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, COOLDOWN_HOURS, COOLDOWN_MINUTES, KEY_DURATIONS
from database import (
    init_db, create_user, create_key,
    get_active_key_for_user, get_stats,
    deactivate_user_keys,
    get_site_id_for_user, reset_activation_for_user,
    get_all_users_paginated, get_total_users_count,
    get_user_by_telegram_id, set_user_banned, set_user_can_get_keys,
    admin_create_key, revoke_all_user_keys, delete_key_by_id,
)
from keyboards import (
    main_menu, close_inline, duration_menu, admin_menu,
    my_keys_menu,
    admin_panel_menu, admin_users_page, admin_user_profile_keyboard,
    admin_revoke_confirm_keyboard, admin_give_duration_keyboard,
    admin_give_confirm_keyboard, admin_broadcast_keyboard,
)

router = Router()

# ===== ЧАСОВОЙ ПОЯС =====
LOCAL_TZ = timezone(timedelta(hours=3))

# ===== ПАГИНАЦИЯ =====
USERS_PER_PAGE = 10


# ===== ФОРМАТИРОВАНИЕ =====

def parse_iso_utc(iso_str: str) -> datetime:
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
    try:
        dt = parse_iso_utc(iso_str)
        dt_local = dt.astimezone(LOCAL_TZ)
        return dt_local.strftime("%d.%m.%Y - %H:%M")
    except Exception as e:
        print(f"⚠️ Ошибка форматирования даты '{iso_str}': {e}")
        return str(iso_str)


def fmt_time_left(seconds: int) -> str:
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
    return "\n".join([
        "<b>🤖 Бот активации HITREVIL!</b>",
        "",
        '<b>🔑 Для получения ключа нажмите "🔑 Получить ключ"</b>',
    ])


def build_menu_text(user_key: dict | None = None, site_id: str | None = None) -> str:
    lines = [
        "<b>🤖 Бот активации HITREVIL!</b>",
        "",
        '<b>🔑 Для получения ключа нажмите "🔑 Получить ключ"</b>',
        "",
    ]

    if site_id:
        lines.append(f"<b>Ваш id в HITREVIL :</b> <code>{site_id}</code>")
        lines.append("")

    if user_key and user_key.get("key"):
        lines.append(f"<b>✅ Ваш ключ :</b> <code>{user_key['key']}</code>")
        lines.append(f"<b>🕒 Активен до :</b> {fmt_dt(user_key['expires_at'])}")

    return "\n".join(lines)


# ===== /start =====

@router.message(CommandStart())
async def cmd_start(message: Message):
    init_db()
    create_user(message.from_user.id, message.from_user.username or "")

    # Проверка на бан
    user = get_user_by_telegram_id(message.from_user.id)
    if user and user.get("banned", 0):
        await message.answer("🚫 Вы заблокированы в боте.")
        return

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

    # Проверка на бан
    user = get_user_by_telegram_id(message.from_user.id)
    if user and user.get("banned", 0):
        await message.answer("🚫 Вы заблокированы в боте.")
        return

    # Проверка на запрет получения
    if user and not user.get("can_get_keys", 1):
        await message.answer("🚫 Получение ключей недоступно.")
        return

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

    try:
        await callback.message.delete()
    except Exception:
        pass

    create_key(callback.from_user.id, duration_seconds)

    is_admin = callback.from_user.id in ADMIN_IDS

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
        await message.answer(
            "<b>❌ У тебя нет активных ключей!</b>",
            reply_markup=close_inline(),
            parse_mode="HTML",
        )
        return

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

    try:
        await callback.message.delete()
    except Exception:
        pass

    if existing:
        deactivate_user_keys(callback.from_user.id)
        reset_activation_for_user(callback.from_user.id)

    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.answer(
        build_start_text(),
        reply_markup=main_menu(is_admin=is_admin),
        parse_mode="HTML",
    )
    await callback.answer()


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
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )


# ===== АДМИН: ГЛАВНАЯ =====

@router.callback_query(F.data == "admin_back_to_main")
async def admin_back_to_main(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "<b>⚙️ Админ панель</b>",
            reply_markup=admin_panel_menu(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


# ===== АДМИН: СТАТИСТИКА =====

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
    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_panel_menu(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


# ===== АДМИН: ПОЛЬЗОВАТЕЛИ =====

@router.callback_query(F.data.startswith("admin_users:"))
async def admin_users_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        page = int(callback.data.split(":")[1])
    except Exception:
        page = 1

    total = get_total_users_count()
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    users = get_all_users_paginated(page, USERS_PER_PAGE)

    lines = ["<b>👥 Пользователи</b>", ""]

    user_buttons = []
    for u in users:
        tid = u["telegram_id"]
        uname = u.get("username") or "—"
        has_key = get_active_key_for_user(tid)
        status = "🟢" if has_key else "🔴"
        label = f"{tid} | @{uname} {status}"
        user_buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin_profile:{tid}")])

    pagination_kb = admin_users_page(page, total_pages)
    combined = user_buttons + pagination_kb.inline_keyboard

    keyboard = InlineKeyboardMarkup(inline_keyboard=combined)

    text = "\n".join(lines)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        try:
            await callback.message.delete()
            await callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data == "admin_users_noop")
async def admin_users_noop(callback: CallbackQuery):
    await callback.answer()


# ===== АДМИН: ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ =====

@router.callback_query(F.data.startswith("admin_profile:"))
async def admin_user_profile(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    user = get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    active_key = get_active_key_for_user(tid)

    uname = user.get("username") or "—"
    site_id = get_site_id_for_user(tid)
    banned = user.get("banned", 0)
    can_get = user.get("can_get_keys", 1)

    lines = [
        "<b>👥 Пользователь</b>",
        "",
        f"<b>◼️ TG :</b> <code>{tid}</code>",
        f"<b>◼️ Имя :</b> {user.get('username') or '—'}",
        f"<b>◼️ User :</b> @{uname}",
        f"<b>◼️ HITREVIL ID :</b> <code>{site_id or '—'}</code>",
    ]

    if active_key:
        lines.append(f"<b>◼️ Активный ключ :</b> {fmt_dt(active_key['expires_at'])}")
        lines.append(f"<b>◼️ Ключ :</b> <code>{active_key['key']}</code>")
    else:
        lines.append("<b>◼️ Активный ключ :</b> 🚫 Нет")
        lines.append("<b>◼️ Ключ :</b> ➖")

    lines.append(f"<b>◼️ Получение ключей :</b> {'✅ Доступно' if can_get else '🚫 Недоступно'}")
    lines.append(f"<b>◼️ Заблокирован в боте :</b> {'✅ Да' if banned else '🚫 Нет'}")

    text = "\n".join(lines)

    keyboard = admin_user_profile_keyboard(user, bool(active_key))

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        try:
            await callback.message.delete()
            await callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data == "admin_close_profile")
async def admin_close_profile(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "admin_close_to_panel")
async def admin_close_to_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== АДМИН: ОТЗЫВ КЛЮЧА =====

@router.callback_query(F.data.startswith("admin_revoke:"))
async def admin_revoke_key(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    text = (
        "<b>Вы хотите отозвать ключ?</b>\n\n"
        "<b>Пользователь потеряет доступ к HITREVIL!</b>"
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_revoke_confirm_keyboard(tid),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("admin_revoke_cancel:"))
async def admin_revoke_cancel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    callback.data = f"admin_profile:{tid}"
    await admin_user_profile(callback)


@router.callback_query(F.data.startswith("admin_revoke_confirm:"))
async def admin_revoke_confirm(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    active_key = get_active_key_for_user(tid)

    revoke_all_user_keys(tid)
    reset_activation_for_user(tid)

    try:
        await callback.message.delete()
    except Exception:
        pass

    if active_key:
        try:
            text = (
                f"<b>❗ Ваш ключ {active_key['key']} отозван!</b>\n\n"
                "<b>Доступ к HITREVIL закрыт.</b>"
            )
            await callback.bot.send_message(
                chat_id=tid,
                text=text,
                reply_markup=close_inline(),
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"⚠️ Не удалось уведомить {tid}: {e}")

    await callback.message.answer(
        f"<b>✅ Ключ пользователя <code>{tid}</code> отозван</b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )

    await callback.answer()


# ===== АДМИН: ВЫДАЧА КЛЮЧА =====

@router.callback_query(F.data.startswith("admin_give:"))
async def admin_give_key(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    text = "<b>На сколько выдать ключ?</b>"

    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_give_duration_keyboard(tid),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("admin_give_dur:"))
async def admin_give_duration(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        parts = callback.data.split(":")
        tid = int(parts[1])
        duration_code = parts[2]
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    if duration_code not in KEY_DURATIONS:
        await callback.answer("Неверный срок", show_alert=True)
        return

    duration_seconds = KEY_DURATIONS[duration_code]

    new_key = admin_create_key(tid, duration_seconds)

    user = get_user_by_telegram_id(tid)
    uname = user.get("username") if user else "—"

    text = "\n".join([
        f"<b>Выдача ключа пользователю @{uname}.</b>",
        "",
        f"<b>◼️ Ключ :</b> <code>{new_key['key']}</code>",
        f"<b>◼️ Активен до :</b> <code>{fmt_dt(new_key['expires_at'])}</code>",
    ])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=admin_give_confirm_keyboard(tid),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("admin_give_cancel:"))
async def admin_give_cancel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    # Удаляем последний созданный ключ
    active_key = get_active_key_for_user(tid)
    if active_key:
        delete_key_by_id(active_key["id"])

    callback.data = f"admin_profile:{tid}"
    await admin_user_profile(callback)


@router.callback_query(F.data.startswith("admin_give_confirm:"))
async def admin_give_confirm(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    active_key = get_active_key_for_user(tid)
    if not active_key:
        await callback.answer("Ключ не найден", show_alert=True)
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    try:
        text = "\n".join([
            "<b>✅ Вам выдан ключ!</b>",
            "",
            f"<b>🔑 Ваш ключ :</b> <code>{active_key['key']}</code>",
            f"<b>🕒 Активен до :</b> <code>{fmt_dt(active_key['expires_at'])}</code>",
        ])
        await callback.bot.send_message(
            chat_id=tid,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"⚠️ Не удалось уведомить {tid}: {e}")

    await callback.message.answer(
        f"<b>✅ Ключ выдан пользователю <code>{tid}</code></b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )

    await callback.answer()


# ===== АДМИН: ДОСТУП К ПОЛУЧЕНИЮ КЛЮЧЕЙ =====

@router.callback_query(F.data.startswith("admin_toggle_keys:"))
async def admin_toggle_keys(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    user = get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    current = user.get("can_get_keys", 1)
    new_value = 0 if current else 1

    set_user_can_get_keys(tid, bool(new_value))

    try:
        if new_value:
            text = (
                "<b>✅ Вам снова доступно получение ключей!</b>\n\n"
                "<b>Воспользуйтесь меню ниже ⬇️.</b>"
            )
        else:
            text = "<b>❗ Получение ключей вам недоступно!</b>"

        await callback.bot.send_message(
            chat_id=tid,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"⚠️ Не удалось уведомить {tid}: {e}")

    callback.data = f"admin_profile:{tid}"
    await admin_user_profile(callback)


# ===== АДМИН: БЛОКИРОВКА =====

@router.callback_query(F.data.startswith("admin_toggle_ban:"))
async def admin_toggle_ban(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    try:
        tid = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return

    user = get_user_by_telegram_id(tid)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    current = user.get("banned", 0)
    new_value = 0 if current else 1

    set_user_banned(tid, bool(new_value))

    try:
        if not new_value:
            text = "<b>✅ Бот вам снова доступен, воспользуйтесь меню ниже ⬇️.</b>"
            await callback.bot.send_message(
                chat_id=tid,
                text=text,
                reply_markup=main_menu(is_admin=False),
                parse_mode="HTML",
            )
    except Exception as e:
        print(f"⚠️ Не удалось уведомить {tid}: {e}")

    callback.data = f"admin_profile:{tid}"
    await admin_user_profile(callback)


# ===== АДМИН: РАССЫЛКА =====

broadcast_waiting = set()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    broadcast_waiting.add(callback.from_user.id)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "<b>Отправьте сообщение для рассылки</b>",
        reply_markup=admin_broadcast_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_cancel")
async def admin_broadcast_cancel(callback: CallbackQuery):
    broadcast_waiting.discard(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.text, lambda m: m.from_user.id in broadcast_waiting)
async def admin_broadcast_send(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if message.from_user.id not in broadcast_waiting:
        return

    broadcast_waiting.discard(message.from_user.id)

    broadcast_text = message.text

    # Собираем всех пользователей
    total = get_total_users_count()
    all_users = []
    page = 1
    while True:
        users = get_all_users_paginated(page, 100)
        if not users:
            break
        all_users.extend(users)
        if len(users) < 100:
            break
        page += 1

    sent = 0
    failed = 0

    status_msg = await message.answer(
        f"<b>📤 Начинаю рассылку для {len(all_users)} пользователей...</b>",
        parse_mode="HTML",
    )

    for u in all_users:
        try:
            await message.bot.send_message(
                chat_id=u["telegram_id"],
                text=broadcast_text,
            )
            sent += 1
        except Exception:
            failed += 1

    try:
        await status_msg.delete()
    except Exception:
        pass

    await message.answer(
        f"<b>✅ Рассылка завершена</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        reply_markup=admin_panel_menu(),
        parse_mode="HTML",
    )