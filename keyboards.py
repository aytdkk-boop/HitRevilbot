# keyboards.py
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню. Всегда две кнопки: Получить ключ и Мои ключи."""
    buttons = [
        [KeyboardButton(text="🔑 Получить ключ"), KeyboardButton(text="✅ Мои ключи")],
    ]

    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Админка")])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def duration_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Тестовый режим - 5 минут", callback_data="dur:test")],
            [
                InlineKeyboardButton(text="🕒 2 часа", callback_data="dur:2h"),
                InlineKeyboardButton(text="🕒 4 часа", callback_data="dur:4h"),
                InlineKeyboardButton(text="🕒 6 часов", callback_data="dur:6h"),
            ],
            [
                InlineKeyboardButton(text="🕒 12 часов", callback_data="dur:12h"),
                InlineKeyboardButton(text="🕒 24 часа", callback_data="dur:24h"),
                InlineKeyboardButton(text="🕒 48 часов", callback_data="dur:48h"),
            ],
            [InlineKeyboardButton(text="🕒 1 месяц", callback_data="dur:1m")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_msg")],
        ]
    )


def close_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть", callback_data="close_msg")]]
    )


def my_keys_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Сбросить ключ", callback_data="reset_key")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_msg")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )


# ===== АДМИН-КЛАВИАТУРЫ =====

def admin_panel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users:1")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💯 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🔐 API", callback_data="admin_api")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back_to_main")],
        ]
    )


def admin_api_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ключ", callback_data="admin_api_add")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back_to_main")],
        ]
    )


def admin_api_add_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_api_add_cancel")],
        ]
    )


def admin_users_page(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_users:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="admin_users_noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_users:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close_to_panel")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_profile_keyboard(user: dict, has_active_key: bool) -> InlineKeyboardMarkup:
    buttons = []

    if has_active_key:
        buttons.append([InlineKeyboardButton(text="🚫 Отозвать ключ", callback_data=f"admin_revoke:{user['telegram_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text="➕ Выдать ключ", callback_data=f"admin_give:{user['telegram_id']}")])

    can_get = user.get("can_get_keys", 1)
    if can_get:
        buttons.append([InlineKeyboardButton(text="✅ Получение ключей", callback_data=f"admin_toggle_keys:{user['telegram_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text="⬜ Получение ключей", callback_data=f"admin_toggle_keys:{user['telegram_id']}")])

    banned = user.get("banned", 0)
    if banned:
        buttons.append([InlineKeyboardButton(text="✅ Заблокирован", callback_data=f"admin_toggle_ban:{user['telegram_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text="⬜ Заблокирован", callback_data=f"admin_toggle_ban:{user['telegram_id']}")])

    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close_profile")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_revoke_confirm_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"admin_revoke_confirm:{telegram_id}"),
                InlineKeyboardButton(text="🚫 Нет", callback_data=f"admin_revoke_cancel:{telegram_id}"),
            ],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"admin_profile:{telegram_id}")],
        ]
    )


def admin_give_duration_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Тестовый режим - 5 минут", callback_data=f"admin_give_dur:{telegram_id}:test")],
            [
                InlineKeyboardButton(text="🕒 2 часа", callback_data=f"admin_give_dur:{telegram_id}:2h"),
                InlineKeyboardButton(text="🕒 4 часа", callback_data=f"admin_give_dur:{telegram_id}:4h"),
                InlineKeyboardButton(text="🕒 6 часов", callback_data=f"admin_give_dur:{telegram_id}:6h"),
            ],
            [
                InlineKeyboardButton(text="🕒 12 часов", callback_data=f"admin_give_dur:{telegram_id}:12h"),
                InlineKeyboardButton(text="🕒 24 часа", callback_data=f"admin_give_dur:{telegram_id}:24h"),
                InlineKeyboardButton(text="🕒 48 часов", callback_data=f"admin_give_dur:{telegram_id}:48h"),
            ],
            [InlineKeyboardButton(text="🕒 1 месяц", callback_data=f"admin_give_dur:{telegram_id}:1m")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data=f"admin_profile:{telegram_id}")],
        ]
    )


def admin_give_confirm_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_give_confirm:{telegram_id}"),
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_give_cancel:{telegram_id}"),
            ],
        ]
    )


def admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin_broadcast_cancel")],
        ]
    )