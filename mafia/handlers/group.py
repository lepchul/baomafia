"""Группа: /newgame, /startgame, /stop, /leave и приветствие при добавлении."""

import contextlib

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command
from aiogram.types import ChatMemberUpdated, Message

from .. import database as db
from .. import texts as T
from ..config import MIN_PLAYERS
from ..game import Phase, manager

router = Router(name="group")
GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


async def check_admin(message: Message) -> bool:
    # анонимный администратор пишет от имени чата
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True
    if await is_admin(message.bot, message.chat.id, message.from_user.id):
        return True
    await message.reply(T.ONLY_ADMIN)
    return False


# --------------------------------------------------------------------------- #
#                          Бота добавили в группу                              #
# --------------------------------------------------------------------------- #
@router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added(event: ChatMemberUpdated) -> None:
    if event.chat.type not in GROUPS:
        return
    await db.remember_chat(event.chat.id, event.chat.title or "")
    with contextlib.suppress(TelegramAPIError):
        await event.bot.send_message(event.chat.id, T.ADDED_TO_GROUP)


# --------------------------------------------------------------------------- #
#                                  /newgame                                    #
# --------------------------------------------------------------------------- #
@router.message(Command("newgame"), F.chat.type.in_(GROUPS))
async def cmd_newgame(message: Message) -> None:
    if not await check_admin(message):
        return
    if manager.is_running(message.chat.id):
        await message.reply(T.GAME_ALREADY_RUNNING)
        return

    await db.remember_chat(message.chat.id, message.chat.title or "")
    me = await message.bot.me()
    manager.create(message.bot, message.chat.id, message.chat.title or "чат", me.username)


@router.message(Command("startgame"), F.chat.type.in_(GROUPS))
async def cmd_startgame(message: Message) -> None:
    game = manager.get(message.chat.id)
    if not game or game.phase is Phase.FINISHED:
        await message.reply(T.NO_GAME)
        return
    if game.phase is not Phase.REGISTRATION:
        await message.reply("🎲 Игра уже идёт.")
        return
    if not await check_admin(message):
        return
    if len(game.players) < MIN_PLAYERS:
        await message.reply(
            f"😔 Пока только {len(game.players)} из {MIN_PLAYERS} нужных игроков."
        )
        return
    game.force_start()


@router.message(Command("stop"), F.chat.type.in_(GROUPS))
async def cmd_stop(message: Message) -> None:
    if not manager.is_running(message.chat.id):
        await message.reply(T.NO_GAME)
        return
    if not await check_admin(message):
        return
    await manager.stop(message.chat.id)


@router.message(Command("leave"), F.chat.type.in_(GROUPS))
async def cmd_leave_group(message: Message) -> None:
    game = manager.get(message.chat.id)
    if not game:
        await message.reply(T.NO_GAME)
        return
    if game.remove_player(message.from_user.id):
        await message.reply(T.LEFT)
        await game.refresh_registration()
    else:
        await message.reply("Выйти можно только во время регистрации.")


@router.message(Command("shop"), F.chat.type.in_(GROUPS))
async def cmd_shop_group(message: Message) -> None:
    await message.reply(T.SHOP_ONLY_PRIVATE)


@router.message(Command("help"), F.chat.type.in_(GROUPS))
async def cmd_help_group(message: Message) -> None:
    await message.reply(T.HELP)


@router.message(Command("roles"), F.chat.type.in_(GROUPS))
async def cmd_roles_group(message: Message) -> None:
    from .. import roles as R

    await message.reply(R.roles_overview())
