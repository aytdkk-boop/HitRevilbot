# keyboards.py
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Главное меню.
    Кнопка «Мои ключи» показывается всегда.
    Кнопка «Админка» — только для админов.
    """
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
    """Меню выбора срока ключа."""
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
    """Простая кнопка «Закрыть»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть", callback_data="close_msg")]]
    )


def my_keys_menu() -> InlineKeyboardMarkup:
    """Кнопки в разделе «Мои ключи»: сбросить и закрыть."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Сбросить ключ", callback_data="reset_key")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_msg")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    """Меню админа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ]
    )