"""Bao Mafia — точка входа.

Запуск:
    pip install -r requirements.txt
    cp .env.example .env   # и вписать BOT_TOKEN
    python main.py
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from mafia import database as db
from mafia.config import BOT_TOKEN
from mafia.handlers import setup_routers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("baomafia")

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Запустить бота"),
    BotCommand(command="shop", description="Магазин"),
    BotCommand(command="profile", description="Профиль и инвентарь"),
    BotCommand(command="roles", description="Список ролей"),
    BotCommand(command="leave", description="Выйти из игры"),
    BotCommand(command="help", description="Справка"),
]

GROUP_COMMANDS = [
    BotCommand(command="newgame", description="Новая игра"),
    BotCommand(command="startgame", description="Окончить регистрацию и начать игру"),
    BotCommand(command="stop", description="Окончание игры"),
    BotCommand(command="leave", description="Выйти из игры"),
    BotCommand(command="roles", description="Список ролей"),
    BotCommand(command="help", description="Справка"),
]


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен.")
        sys.exit(1)

    await db.init()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(setup_routers())

    await set_commands(bot)
    me = await bot.me()
    log.info("Bao Mafia запущен как @%s", me.username)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен")
