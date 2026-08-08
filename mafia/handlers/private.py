"""Личка: приветствие, магазин, профиль, вход в игру по deep-link."""

import contextlib

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import database as db
from .. import keyboards as kb
from .. import roles as R
from .. import texts as T
from ..config import SHOP_ITEMS
from ..game import Phase, manager

router = Router(name="private")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def _bot_username(message_or_cb) -> str:
    me = await message_or_cb.bot.me()
    return me.username


# --------------------------------------------------------------------------- #
#                                    /start                                    #
# --------------------------------------------------------------------------- #
@router.message(CommandStart(deep_link=True))
async def start_deeplink(message: Message, command: CommandObject) -> None:
    await db.ensure_user(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    payload = command.args or ""

    if not payload.startswith("join_"):
        await message.answer(T.START, reply_markup=kb.start_kb(await _bot_username(message)))
        return

    try:
        chat_id = kb.decode_chat(payload[5:])
    except ValueError:
        await message.answer(T.NO_GAME)
        return

    game = manager.get(chat_id)
    if not game or game.phase is Phase.FINISHED:
        await message.answer(T.NO_GAME)
        return

    result = game.add_player(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    if result == "already":
        await message.answer(T.ALREADY_JOINED)
        return
    if result == "started":
        await message.answer("🎲 Регистрация уже закрыта, игра идёт.")
        return
    if result == "full":
        await message.answer("😿 В игре уже максимум игроков.")
        return

    await message.answer(T.JOINED_PRIVATE.format(chat_title=game.chat_title))
    await game.refresh_registration()
    with contextlib.suppress(TelegramAPIError):
        await message.bot.send_message(
            chat_id,
            f"➕ {game.players[message.from_user.id].mention} присоединился(лась) к игре.",
        )


@router.message(CommandStart())
async def start(message: Message) -> None:
    await db.ensure_user(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    await message.answer(T.START, reply_markup=kb.start_kb(await _bot_username(message)))


@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery) -> None:
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            T.START, reply_markup=kb.start_kb(await _bot_username(call))
        )
    await call.answer()


# --------------------------------------------------------------------------- #
#                                    Магазин                                   #
# --------------------------------------------------------------------------- #
@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
    await db.ensure_user(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    balance = await db.get_balance(message.from_user.id)
    await message.answer(T.shop(balance), reply_markup=kb.shop_kb())


@router.callback_query(F.data == "shop")
async def cb_shop(call: CallbackQuery) -> None:
    balance = await db.get_balance(call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(T.shop(balance), reply_markup=kb.shop_kb())
    await call.answer()


@router.callback_query(F.data.startswith("item:"))
async def cb_item(call: CallbackQuery) -> None:
    item_key = call.data.split(":", 1)[1]
    if item_key not in SHOP_ITEMS:
        await call.answer("Товар не найден", show_alert=True)
        return
    balance = await db.get_balance(call.from_user.id)
    owned = await db.get_item_amount(call.from_user.id, item_key)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            T.item_card(item_key, balance, owned), reply_markup=kb.item_kb(item_key)
        )
    await call.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery) -> None:
    item_key = call.data.split(":", 1)[1]
    ok, reason, balance = await db.buy_item(call.from_user.id, item_key)
    if not ok:
        await call.answer(T.NOT_ENOUGH_COINS, show_alert=True)
        return
    owned = await db.get_item_amount(call.from_user.id, item_key)
    await call.answer(T.BOUGHT, show_alert=True)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            T.item_card(item_key, balance, owned), reply_markup=kb.item_kb(item_key)
        )


# --------------------------------------------------------------------------- #
#                              Профиль и справка                               #
# --------------------------------------------------------------------------- #
@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await db.ensure_user(
        message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    stats = await db.get_stats(message.from_user.id)
    inv = await db.get_inventory(message.from_user.id)
    await message.answer(
        T.profile(message.from_user.full_name, stats, inv), reply_markup=kb.back_to_start_kb()
    )


@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery) -> None:
    stats = await db.get_stats(call.from_user.id)
    inv = await db.get_inventory(call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            T.profile(call.from_user.full_name, stats, inv),
            reply_markup=kb.back_to_start_kb(),
        )
    await call.answer()


@router.callback_query(F.data == "roles")
async def cb_roles(call: CallbackQuery) -> None:
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(R.roles_overview(), reply_markup=kb.back_to_start_kb())
    await call.answer()


@router.message(Command("roles"))
async def cmd_roles(message: Message) -> None:
    await message.answer(R.roles_overview())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(T.HELP)


@router.message(Command("leave"))
async def cmd_leave_private(message: Message) -> None:
    game = manager.find_by_user(message.from_user.id)
    if not game:
        await message.answer(T.NOT_IN_GAME)
        return
    if game.remove_player(message.from_user.id):
        await message.answer(T.LEFT)
        await game.refresh_registration()
    else:
        await message.answer("🎲 Игра уже началась, выйти нельзя.")
