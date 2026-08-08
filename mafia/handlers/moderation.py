"""Порядок в чате: ночью тишина, посторонние и мёртвые не пишут."""

import contextlib
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from ..game import Phase, manager

log = logging.getLogger(__name__)

router = Router(name="moderation")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message()
async def guard(message: Message) -> None:
    game = manager.get(message.chat.id)
    if not game or game.phase in (Phase.REGISTRATION, Phase.FINISHED):
        return

    # команды и служебные сообщения не трогаем
    if message.text and message.text.startswith("/"):
        return
    if not message.from_user:
        return
    if message.from_user.is_bot:
        return

    player = game.players.get(message.from_user.id)

    reason = None
    if game.phase is Phase.NIGHT:
        reason = "night"
    elif player is None:
        reason = "not_playing"
    elif not player.alive:
        reason = "dead"

    if reason is None:
        return

    try:
        await message.delete()
    except TelegramAPIError as e:
        log.info("не удалось удалить сообщение в %s: %s", message.chat.id, e)
        return

    # мёртвым и зрителям подсказываем в личку, чтобы не спамить в чат
    hints = {
        "night": "🌙 Ночью в чате тишина — сообщение удалено.",
        "not_playing": "🙈 Сейчас идёт игра, писать могут только участники.",
        "dead": "☠️ Мёртвые не разговаривают.",
    }
    with contextlib.suppress(TelegramAPIError):
        await message.bot.send_message(message.from_user.id, hints[reason])
