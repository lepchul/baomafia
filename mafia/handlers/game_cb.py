"""Игровые колбэки: ночные действия, нож, предметы, голосование."""

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from .. import keyboards as kb
from .. import texts as T
from ..game import Phase, manager

router = Router(name="game_cb")


def _game(token: str):
    try:
        chat_id = kb.decode_chat(token)
    except ValueError:
        return None
    game = manager.get(chat_id)
    if not game or game.phase is Phase.FINISHED:
        return None
    return game


async def _strip_keyboard(call: CallbackQuery) -> None:
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_reply_markup(reply_markup=None)


# --------------------------------------------------------------------------- #
#                             Ночные действия                                  #
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("mode:"))
async def cb_mode(call: CallbackQuery) -> None:
    _, mode, token = call.data.split(":", 2)
    game = _game(token)
    if not game:
        await call.answer(T.NO_GAME, show_alert=True)
        return
    text = await game.handle_mode(call.from_user.id, mode)
    await _strip_keyboard(call)
    await call.answer(text[:200], show_alert=False)


@router.callback_query(F.data.startswith("act:"))
async def cb_action(call: CallbackQuery) -> None:
    _, action, token, target = call.data.split(":", 3)
    game = _game(token)
    if not game:
        await call.answer(T.NO_GAME, show_alert=True)
        return
    text = await game.handle_action(call.from_user.id, action, int(target))
    await _strip_keyboard(call)
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(text)
    await call.answer()


# --------------------------------------------------------------------------- #
#                                    Нож                                       #
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("knife:"))
async def cb_knife(call: CallbackQuery) -> None:
    token = call.data.split(":", 1)[1]
    game = _game(token)
    if not game:
        await call.answer(T.NO_GAME, show_alert=True)
        return

    player = game.players.get(call.from_user.id)
    if not player or not player.alive:
        await call.answer(T.DEAD_CANT_ACT, show_alert=True)
        return
    if not player.has_knife:
        await call.answer(T.ITEM_GONE, show_alert=True)
        return
    if player.knife_used_round == game.round:
        await call.answer(T.KNIFE_USED_THIS_ROUND, show_alert=True)
        return

    await _strip_keyboard(call)
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(
            T.KNIFE_PICK,
            reply_markup=kb.targets_kb(
                "knife", game.chat_id, game.targets({call.from_user.id})
            ),
        )
    await call.answer()


# --------------------------------------------------------------------------- #
#                          Активация предметов                                 #
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("use:"))
async def cb_use_item(call: CallbackQuery) -> None:
    _, item_key, token = call.data.split(":", 2)
    await _strip_keyboard(call)

    if item_key == "no":
        await call.answer(T.ITEM_DECLINED)
        return

    game = _game(token)
    if not game:
        await call.answer(T.NO_GAME, show_alert=True)
        return

    text = await game.activate_item(call.from_user.id, item_key)
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(text)
    await call.answer()


# --------------------------------------------------------------------------- #
#                                Голосование                                   #
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(call: CallbackQuery) -> None:
    _, token, target = call.data.split(":", 2)
    game = _game(token)
    if not game:
        await call.answer(T.NO_GAME, show_alert=True)
        return
    text = await game.handle_vote(call.from_user.id, int(target))
    await call.answer(text[:200], show_alert=False)
