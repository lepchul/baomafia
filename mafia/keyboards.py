"""Инлайн-клавиатуры."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import CURRENCY, SHOP_ITEMS


def encode_chat(chat_id: int) -> str:
    """chat_id -> строка, безопасная для deep-link payload."""
    return str(chat_id).replace("-", "m")


def decode_chat(token: str) -> int:
    return int(token.replace("m", "-"))


# --------------------------------------------------------------------------- #
#                                    Старт                                     #
# --------------------------------------------------------------------------- #
def start_kb(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
            [
                InlineKeyboardButton(
                    text="➕ Добавить в группу",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(text="🎭 Роли", callback_data="roles"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            ],
        ]
    )


def back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="home")]]
    )


# --------------------------------------------------------------------------- #
#                                    Магазин                                   #
# --------------------------------------------------------------------------- #
def shop_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, meta in SHOP_ITEMS.items():
        builder.button(
            text=f"{meta['emoji']} {meta['title']} - {meta['price']} {CURRENCY}",
            callback_data=f"item:{key}",
        )
    builder.button(text="⬅️ Назад", callback_data="home")
    builder.adjust(1)
    return builder.as_markup()


def item_kb(item_key: str) -> InlineKeyboardMarkup:
    meta = SHOP_ITEMS[item_key]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💳 Купить за {meta['price']} {CURRENCY}",
                    callback_data=f"buy:{item_key}",
                )
            ],
            [InlineKeyboardButton(text="⬅️ В магазин", callback_data="shop")],
        ]
    )


# --------------------------------------------------------------------------- #
#                                  Регистрация                                 #
# --------------------------------------------------------------------------- #
def join_kb(bot_username: str, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Присоединиться",
                    url=f"https://t.me/{bot_username}?start=join_{encode_chat(chat_id)}",
                )
            ]
        ]
    )


# --------------------------------------------------------------------------- #
#                              Игровые клавиатуры                              #
# --------------------------------------------------------------------------- #
def targets_kb(
    action: str,
    chat_id: int,
    targets: list[tuple[int, str]],
    *,
    skip: bool = True,
) -> InlineKeyboardMarkup:
    """Кнопки со списком целей. callback: `act:{action}:{chat}:{user_id}`."""
    builder = InlineKeyboardBuilder()
    for user_id, name in targets:
        builder.button(text=name, callback_data=f"act:{action}:{encode_chat(chat_id)}:{user_id}")
    if skip:
        builder.button(text="💤 Пропустить", callback_data=f"act:{action}:{encode_chat(chat_id)}:0")
    builder.adjust(1)
    return builder.as_markup()


def commissar_kb(chat_id: int) -> InlineKeyboardMarkup:
    token = encode_chat(chat_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Проверить", callback_data=f"mode:check:{token}")],
            [InlineKeyboardButton(text="🔫 Стрелять", callback_data=f"mode:shot:{token}")],
            [InlineKeyboardButton(text="💤 Пропустить", callback_data=f"mode:skip:{token}")],
        ]
    )


def vote_kb(chat_id: int, targets: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    token = encode_chat(chat_id)
    for user_id, name in targets:
        builder.button(text=name, callback_data=f"vote:{token}:{user_id}")
    builder.button(text="🙈 Воздержаться", callback_data=f"vote:{token}:0")
    builder.adjust(2)
    return builder.as_markup()


def item_offer_kb(chat_id: int, item_key: str) -> InlineKeyboardMarkup:
    token = encode_chat(chat_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Использовать", callback_data=f"use:{item_key}:{token}"
                ),
                InlineKeyboardButton(
                    text="❌ Не сейчас", callback_data=f"use:no:{token}"
                ),
            ]
        ]
    )


def knife_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔪 Пустить нож в ход",
                    callback_data=f"knife:{encode_chat(chat_id)}",
                )
            ]
        ]
    )
