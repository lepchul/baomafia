"""Игровой движок Bao Mafia: фазы, ночные действия, голосование, победа."""

import asyncio
import contextlib
import html
import logging
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import database as db
from . import keyboards as kb
from . import roles as R
from . import texts as T
from .config import (
    CURRENCY,
    DAY_TIME,
    MIN_PLAYERS,
    MAX_PLAYERS,
    NIGHT_TIME,
    REGISTRATION_TIME,
    VOTE_TIME,
)
from .roles import Team

log = logging.getLogger(__name__)


class Phase(str, Enum):
    REGISTRATION = "registration"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    FINISHED = "finished"


@dataclass
class Player:
    user_id: int
    full_name: str
    username: str | None = None
    role_key: str = "civilian"
    alive: bool = True
    death_round: int = 0
    death_reason: str = ""

    # предметы из магазина
    has_knife: bool = False
    knife_used_round: int = -1
    has_cover: bool = False
    ghost_vote: bool = False
    ghost_offered: bool = False

    @property
    def role(self) -> R.Role:
        return R.ROLES[self.role_key]

    @property
    def team(self) -> Team:
        return self.role.team

    @property
    def name(self) -> str:
        return html.escape(self.full_name)[:64]

    @property
    def mention(self) -> str:
        return f'<a href="tg://user?id={self.user_id}">{self.name}</a>'


class Game:
    def __init__(self, bot: Bot, chat_id: int, chat_title: str, bot_username: str):
        self.bot = bot
        self.chat_id = chat_id
        self.chat_title = chat_title
        self.bot_username = bot_username

        self.players: dict[int, Player] = {}
        self.phase: Phase = Phase.REGISTRATION
        self.round: int = 0
        self.winner: Team | None = None

        self.reg_message_id: int | None = None
        self.reg_left: int = REGISTRATION_TIME
        self.pinned_ids: list[int] = []
        self.task: asyncio.Task | None = None

        self._reg_done = asyncio.Event()
        self._night_done = asyncio.Event()
        self._vote_done = asyncio.Event()
        self._interrupt = asyncio.Event()
        self._lock = asyncio.Lock()

        # ночные данные
        self.n_heal: int | None = None
        self.n_lover: int | None = None
        self.n_maniac: int | None = None
        self.n_mafia_votes: dict[int, int] = {}
        self.n_commissar: tuple[str, int] | None = None
        self.n_commissar_mode: dict[int, str] = {}
        self.n_journalist: list[int] = []
        self.n_granny: int | None = None
        self.n_visits: dict[int, list[int]] = defaultdict(list)
        self.n_pending: set[int] = set()

        # голосование
        self.votes: dict[int, int] = {}
        self.vote_message_id: int | None = None

    # ------------------------------------------------------------------ #
    #                              утилиты                                #
    # ------------------------------------------------------------------ #
    @property
    def alive(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    @property
    def dead(self) -> list[Player]:
        return [p for p in self.players.values() if not p.alive]

    def alive_of(self, team: Team) -> list[Player]:
        return [p for p in self.alive if p.team is team]

    @property
    def mafia_alive(self) -> list[Player]:
        return self.alive_of(Team.MAFIA)

    def by_role(self, key: str, only_alive: bool = True) -> list[Player]:
        pool = self.alive if only_alive else list(self.players.values())
        return [p for p in pool if p.role_key == key]

    def targets(self, exclude: set[int] | None = None) -> list[tuple[int, str]]:
        exclude = exclude or set()
        return [(p.user_id, p.full_name[:48]) for p in self.alive if p.user_id not in exclude]

    async def send(self, text: str, **kwargs):
        try:
            return await self.bot.send_message(self.chat_id, text, **kwargs)
        except TelegramAPIError as e:
            log.warning("send to %s failed: %s", self.chat_id, e)
            return None

    async def dm(self, user_id: int, text: str, **kwargs):
        try:
            return await self.bot.send_message(user_id, text, **kwargs)
        except TelegramAPIError as e:
            log.info("dm to %s failed: %s", user_id, e)
            return None

    async def pin(self, message) -> None:
        if not message:
            return
        with contextlib.suppress(TelegramAPIError):
            await self.bot.pin_chat_message(
                self.chat_id, message.message_id, disable_notification=True
            )
            self.pinned_ids.append(message.message_id)

    async def unpin_all(self) -> None:
        for mid in self.pinned_ids:
            with contextlib.suppress(TelegramAPIError):
                await self.bot.unpin_chat_message(self.chat_id, mid)
        self.pinned_ids.clear()

    async def _wait(self, seconds: float, *events: asyncio.Event) -> None:
        events = (*events, self._interrupt)
        waiters = [asyncio.create_task(e.wait()) for e in events]
        try:
            await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waiters:
                w.cancel()

    # ------------------------------------------------------------------ #
    #                            регистрация                              #
    # ------------------------------------------------------------------ #
    def add_player(self, user_id: int, full_name: str, username: str | None) -> str:
        if self.phase is not Phase.REGISTRATION:
            return "started"
        if user_id in self.players:
            return "already"
        if len(self.players) >= MAX_PLAYERS:
            return "full"
        self.players[user_id] = Player(user_id, full_name, username)
        return "ok"

    def remove_player(self, user_id: int) -> bool:
        if self.phase is Phase.REGISTRATION and user_id in self.players:
            del self.players[user_id]
            return True
        return False

    def registration_text(self, seconds_left: int) -> str:
        names = [p.mention for p in self.players.values()]
        return T.registration(names, max(0, seconds_left))

    async def refresh_registration(self, seconds_left: int | None = None) -> None:
        if self.reg_message_id is None or self.phase is not Phase.REGISTRATION:
            return
        if seconds_left is None:
            seconds_left = self.reg_left
        with contextlib.suppress(TelegramAPIError):
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.reg_message_id,
                text=self.registration_text(seconds_left),
                reply_markup=kb.join_kb(self.bot_username, self.chat_id),
            )

    def force_start(self) -> None:
        self._reg_done.set()

    # ------------------------------------------------------------------ #
    #                            главный цикл                             #
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        try:
            ok = await self._registration_phase()
            if not ok:
                return
            await self._setup()
            while self.phase is not Phase.FINISHED:
                await self._night_phase()
                if await self._check_win():
                    break
                await self._day_phase()
                if await self._check_win():
                    break
                await self._voting_phase()
                if await self._check_win():
                    break
            await self._finish()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("game crashed in chat %s", self.chat_id)
            await self.send("💥 Что-то пошло не так, игра остановлена.")
            self.phase = Phase.FINISHED
            await self.unpin_all()

    async def _registration_phase(self) -> bool:
        msg = await self.send(
            self.registration_text(REGISTRATION_TIME),
            reply_markup=kb.join_kb(self.bot_username, self.chat_id),
        )
        if msg:
            self.reg_message_id = msg.message_id
            await self.pin(msg)

        left = REGISTRATION_TIME
        step = 15
        while left > 0 and not self._reg_done.is_set():
            await self._wait(min(step, left), self._reg_done)
            left = max(0, left - step)
            self.reg_left = left
            if not self._reg_done.is_set():
                await self.refresh_registration(left)

        if len(self.players) < MIN_PLAYERS:
            await self.send(T.NOT_ENOUGH_PLAYERS.format(minimum=MIN_PLAYERS))
            self.phase = Phase.FINISHED
            await self.unpin_all()
            return False
        return True

    async def _setup(self) -> None:
        """Раздача ролей и предложение использовать купленные предметы."""
        deck = R.distribute(len(self.players))
        for player, role_key in zip(self.players.values(), deck, strict=True):
            player.role_key = role_key

        for player in self.players.values():
            await self.dm(
                player.user_id,
                T.your_role(player.role.title, player.role.description, self.chat_title),
            )

        # мафия знакомится
        mafia = self.mafia_alive
        if len(mafia) > 1:
            members = "\n".join(f"{p.role.title} — {p.mention}" for p in mafia)
            for p in mafia:
                await self.dm(p.user_id, T.MAFIA_TEAM.format(members=members))

        await self._offer_items()
        await self.send(
            f"🎲 Игра началась! Игроков: {len(self.players)}\n"
            "Роли разосланы в личные сообщения."
        )
        # даём время на активацию предметов
        await self._wait(20)

    async def _offer_items(self) -> None:
        for player in self.players.values():
            inv = await db.get_inventory(player.user_id)
            usable = {}
            if inv.get("knife") and player.team is not Team.MAFIA:
                usable["knife"] = inv["knife"]
            if inv.get("cover") and player.team is Team.MAFIA:
                usable["cover"] = inv["cover"]
            for key, amount in usable.items():
                await self.dm(
                    player.user_id,
                    T.offer_items(self.chat_title, {key: amount}),
                    reply_markup=kb.item_offer_kb(self.chat_id, key),
                )

    # ------------------------------------------------------------------ #
    #                                ночь                                 #
    # ------------------------------------------------------------------ #
    def _reset_night(self) -> None:
        self.n_heal = None
        self.n_lover = None
        self.n_maniac = None
        self.n_mafia_votes = {}
        self.n_commissar = None
        self.n_commissar_mode = {}
        self.n_journalist = []
        self.n_granny = None
        self.n_visits = defaultdict(list)
        self.n_pending = set()

    async def _night_phase(self) -> None:
        self.phase = Phase.NIGHT
        self.round += 1
        self._reset_night()
        self._night_done.clear()

        msg = await self.send(f"{T.NIGHT_FALLS}\n\n{T.night_ambience()}")
        await self.pin(msg)

        await self._send_night_prompts()
        await self._wait(NIGHT_TIME, self._night_done)
        await self._resolve_night()

    async def _send_night_prompts(self) -> None:
        for player in self.alive:
            role = player.role
            if role.night_action:
                self.n_pending.add(player.user_id)

            if player.team is Team.MAFIA:
                exclude = {p.user_id for p in self.mafia_alive}
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb("mafia", self.chat_id, self.targets(exclude)),
                )
            elif role.key == "commissar":
                await self.dm(
                    player.user_id, role.night_prompt, reply_markup=kb.commissar_kb(self.chat_id)
                )
            elif role.key == "doctor":
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb("heal", self.chat_id, self.targets()),
                )
            elif role.key == "lover":
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb(
                        "lover", self.chat_id, self.targets({player.user_id})
                    ),
                )
            elif role.key == "maniac":
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb(
                        "maniac", self.chat_id, self.targets({player.user_id})
                    ),
                )
            elif role.key == "journalist":
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb(
                        "jour1", self.chat_id, self.targets({player.user_id})
                    ),
                )
            elif role.key == "granny":
                await self.dm(
                    player.user_id,
                    role.night_prompt,
                    reply_markup=kb.targets_kb(
                        "granny", self.chat_id, self.targets({player.user_id})
                    ),
                )
            else:
                await self.dm(player.user_id, T.NIGHT_SLEEP)

            # напоминание про нож
            if player.has_knife and player.knife_used_round != self.round:
                await self.dm(
                    player.user_id, T.KNIFE_ACTIVATED, reply_markup=kb.knife_kb(self.chat_id)
                )

    def _maybe_night_done(self) -> None:
        if not self.n_pending:
            self._night_done.set()

    def _mafia_target(self) -> int | None:
        if not self.n_mafia_votes:
            return None
        counter = Counter(v for v in self.n_mafia_votes.values() if v)
        if not counter:
            return None
        top = counter.most_common()
        best = top[0][1]
        leaders = [uid for uid, cnt in top if cnt == best]
        if len(leaders) == 1:
            return leaders[0]
        # спорная ситуация — решает Дон
        for don in self.by_role("don"):
            choice = self.n_mafia_votes.get(don.user_id)
            if choice in leaders:
                return choice
        return random.choice(leaders)

    async def _resolve_night(self) -> None:
        deaths: list[tuple[Player, str]] = []

        def kill(p: Player, reason: str) -> None:
            if p.alive and all(p is not d for d, _ in deaths):
                deaths.append((p, reason))

        mafia_target = self._mafia_target()

        # --- мафия ---
        if mafia_target and mafia_target != self.n_heal:
            victim = self.players.get(mafia_target)
            if victim and victim.alive:
                kill(victim, "mafia")
                if victim.role_key == "kamikaze" and self.mafia_alive:
                    kill(random.choice(self.mafia_alive), "kamikaze")
                if self.n_lover == victim.user_id:
                    for lover in self.by_role("lover"):
                        kill(lover, "lover")

        # --- маньяк ---
        if self.n_maniac and self.n_maniac != self.n_heal:
            victim = self.players.get(self.n_maniac)
            if victim and victim.alive:
                kill(victim, "maniac")

        # --- комиссар ---
        if self.n_commissar:
            mode, target_id = self.n_commissar
            target = self.players.get(target_id)
            if target and target.alive:
                if mode == "shot":
                    kill(target, "commissar")
                    if target.role_key == "kamikaze":
                        for com in self.by_role("commissar"):
                            kill(com, "kamikaze")
                elif mode == "check":
                    is_mafia = target.team is Team.MAFIA and not target.has_cover
                    text = (T.CHECK_MAFIA if is_mafia else T.CHECK_CLEAN).format(
                        name=target.name
                    )
                    for com in self.by_role("commissar"):
                        await self.dm(com.user_id, text)

        # --- журналист ---
        if len(self.n_journalist) == 2:
            a = self.players.get(self.n_journalist[0])
            b = self.players.get(self.n_journalist[1])
            if a and b:
                same = a.team is b.team
                tpl = T.JOURNALIST_SAME if same else T.JOURNALIST_DIFF
                for j in self.by_role("journalist"):
                    await self.dm(j.user_id, tpl.format(a=a.name, b=b.name))

        # --- бабуля ---
        if self.n_granny:
            watched = self.players.get(self.n_granny)
            count = len(self.n_visits.get(self.n_granny, []))
            if watched:
                for g in self.by_role("granny"):
                    await self.dm(
                        g.user_id, T.GRANNY_RESULT.format(name=watched.name, count=count)
                    )

        # --- применяем смерти ---
        lines = [T.NIGHT_OVER, ""]
        if not deaths:
            lines.append(T.NOBODY_DIED)
        for player, reason in deaths:
            player.alive = False
            player.death_round = self.round
            player.death_reason = reason
            lines.append(T.killed(player.mention, player.role.title))

        await self._promote_sergeant(deaths)
        await self.send("\n".join(lines))

        for player, reason in deaths:
            await self._offer_ghost_vote(player, reason)

    async def _promote_sergeant(self, deaths: list[tuple[Player, str]]) -> None:
        commissar_died = any(p.role_key == "commissar" for p, _ in deaths)
        if not commissar_died:
            return
        for sergeant in self.by_role("sergeant"):
            if all(sergeant is not d for d, _ in deaths):
                sergeant.role_key = "commissar"
                await self.dm(sergeant.user_id, T.SERGEANT_PROMOTED)
                return

    async def _offer_ghost_vote(self, player: Player, reason: str) -> None:
        """Предложить «Голосование за умершего» — только не мафии и только
        если игрок умер от рук мафии или на голосовании."""
        if player.ghost_offered or player.ghost_vote:
            return
        if player.team is Team.MAFIA:
            return
        if reason not in ("mafia", "vote"):
            return
        if not await db.get_item_amount(player.user_id, "ghost_vote"):
            return
        player.ghost_offered = True
        await self.dm(
            player.user_id,
            T.GHOST_VOTE_OFFER,
            reply_markup=kb.item_offer_kb(self.chat_id, "ghost_vote"),
        )

    # ------------------------------------------------------------------ #
    #                                день                                 #
    # ------------------------------------------------------------------ #
    async def _day_phase(self) -> None:
        self.phase = Phase.DAY
        alive_list = "\n".join(f"• {p.mention}" for p in self.alive)
        msg = await self.send(
            T.DAY_START.format(round=self.round, alive=alive_list, seconds=DAY_TIME)
        )
        await self.pin(msg)
        await self._wait(DAY_TIME)

    # ------------------------------------------------------------------ #
    #                            голосование                              #
    # ------------------------------------------------------------------ #
    def voters(self) -> list[Player]:
        out = list(self.alive)
        out += [
            p
            for p in self.dead
            if p.ghost_vote and p.team is not Team.MAFIA
        ]
        return out

    async def _voting_phase(self) -> None:
        self.phase = Phase.VOTING
        self.votes = {}
        self._vote_done.clear()

        msg = await self.send(
            T.VOTE_START.format(seconds=VOTE_TIME),
            reply_markup=kb.vote_kb(self.chat_id, self.targets()),
        )
        self.vote_message_id = msg.message_id if msg else None
        await self._wait(VOTE_TIME, self._vote_done)

        if self.vote_message_id:
            with contextlib.suppress(TelegramAPIError):
                await self.bot.edit_message_reply_markup(
                    self.chat_id, self.vote_message_id, reply_markup=None
                )

        await self._resolve_votes()

    async def _resolve_votes(self) -> None:
        counter: Counter[int] = Counter()
        for voter_id, target_id in self.votes.items():
            if not target_id:
                continue
            voter = self.players.get(voter_id)
            weight = 2 if voter and voter.role_key == "mayor" and voter.alive else 1
            counter[target_id] += weight

        if not counter:
            await self.send(T.NOBODY_VOTED)
            return

        top = counter.most_common()
        best = top[0][1]
        leaders = [uid for uid, cnt in top if cnt == best]
        if len(leaders) > 1:
            await self.send(T.VOTE_TIE)
            return

        victim = self.players.get(leaders[0])
        if not victim or not victim.alive:
            await self.send(T.NOBODY_VOTED)
            return

        victim.alive = False
        victim.death_round = self.round
        victim.death_reason = "vote"
        board = "\n".join(
            f"• {self.players[uid].name} — {cnt}" for uid, cnt in top if uid in self.players
        )
        await self.send(f"{T.executed(victim.mention, victim.role.title)}\n\n{board}")
        await self._promote_sergeant([(victim, "vote")])
        await self._offer_ghost_vote(victim, "vote")

    # ------------------------------------------------------------------ #
    #                          обработка колбэков                         #
    # ------------------------------------------------------------------ #
    async def handle_mode(self, user_id: int, mode: str) -> str:
        """Комиссар выбирает: проверить / стрелять / пропустить."""
        player = self.players.get(user_id)
        if not player or not player.alive:
            return T.DEAD_CANT_ACT
        if self.phase is not Phase.NIGHT or player.role_key != "commissar":
            return T.NOT_YOUR_TURN

        if mode == "skip":
            self.n_pending.discard(user_id)
            self._maybe_night_done()
            return "💤 Вы решили не выходить из машины."

        self.n_commissar_mode[user_id] = mode
        action = "check" if mode == "check" else "shot"
        prompt = "🔎 Кого проверим?" if mode == "check" else "🔫 В кого стреляем?"
        await self.dm(
            user_id,
            prompt,
            reply_markup=kb.targets_kb(action, self.chat_id, self.targets({user_id})),
        )
        return "Выбирайте цель ниже 👇"

    async def handle_action(self, user_id: int, action: str, target_id: int) -> str:
        player = self.players.get(user_id)
        if not player:
            return T.NOT_IN_GAME

        if action == "knife":
            return await self._use_knife(player, target_id)

        if self.phase is not Phase.NIGHT:
            return T.NOT_YOUR_TURN
        if not player.alive:
            return T.DEAD_CANT_ACT

        target = self.players.get(target_id) if target_id else None
        if target_id and (not target or not target.alive):
            return "Эта цель недоступна."

        if action == "mafia" and player.team is Team.MAFIA:
            self.n_mafia_votes[user_id] = target_id
            if target:
                self.n_visits[target_id].append(user_id)
                for mate in self.mafia_alive:
                    if mate.user_id != user_id:
                        await self.dm(
                            mate.user_id,
                            f"🕶 {player.name}: {target.name}",
                        )
            result = T.MAFIA_PICK_DONE.format(name=target.name if target else "никто")

        elif action == "heal" and player.role_key == "doctor":
            self.n_heal = target_id or None
            if target:
                self.n_visits[target_id].append(user_id)
            result = T.HEAL_DONE.format(name=target.name if target else "никто")

        elif action == "lover" and player.role_key == "lover":
            self.n_lover = target_id or None
            if target:
                self.n_visits[target_id].append(user_id)
            result = T.LOVER_DONE.format(name=target.name if target else "никто")

        elif action == "maniac" and player.role_key == "maniac":
            self.n_maniac = target_id or None
            if target:
                self.n_visits[target_id].append(user_id)
            result = T.MANIAC_DONE.format(name=target.name if target else "никто")

        elif action in ("check", "shot") and player.role_key == "commissar":
            if target:
                self.n_commissar = (action, target_id)
                self.n_visits[target_id].append(user_id)
                result = T.SHOT_DONE if action == "shot" else "🔎 Досье будет к утру."
            else:
                result = "💤 Вы решили не выходить из машины."

        elif action == "jour1" and player.role_key == "journalist":
            if not target:
                result = "💤 Сегодня выпуска не будет."
            else:
                self.n_journalist = [target_id]
                await self.dm(
                    user_id,
                    T.JOURNALIST_PICK_SECOND,
                    reply_markup=kb.targets_kb(
                        "jour2", self.chat_id, self.targets({user_id, target_id}), skip=False
                    ),
                )
                return "Выбирайте второго 👇"

        elif action == "jour2" and player.role_key == "journalist":
            if target and self.n_journalist:
                self.n_journalist.append(target_id)
            result = "📰 Материал в работе."

        elif action == "granny" and player.role_key == "granny":
            self.n_granny = target_id or None
            result = "👵 Вы придвинули стул к окну."

        else:
            return T.NOT_YOUR_TURN

        self.n_pending.discard(user_id)
        self._maybe_night_done()
        return result

    async def _use_knife(self, player: Player, target_id: int) -> str:
        if self.phase in (Phase.REGISTRATION, Phase.FINISHED):
            return T.NOT_YOUR_TURN
        if not player.alive:
            return T.DEAD_CANT_ACT
        if not player.has_knife:
            return T.ITEM_GONE
        if player.team is Team.MAFIA:
            return T.KNIFE_NOT_FOR_MAFIA
        if player.knife_used_round == self.round:
            return T.KNIFE_USED_THIS_ROUND

        target = self.players.get(target_id)
        if not target or not target.alive or target.user_id == player.user_id:
            return "Эта цель недоступна."

        player.knife_used_round = self.round
        player.has_knife = False
        target.alive = False
        target.death_round = self.round
        target.death_reason = "knife"

        await self.send(T.knife_strike(target.mention, target.role.title))
        await self._promote_sergeant([(target, "knife")])
        self.n_pending.discard(target.user_id)
        self._maybe_night_done()
        if self._is_over():
            self._interrupt.set()
        return f"🔪 Готово. {target.name} больше нет."

    async def handle_vote(self, user_id: int, target_id: int) -> str:
        if self.phase is not Phase.VOTING:
            return T.NOT_YOUR_TURN
        player = self.players.get(user_id)
        if not player:
            return T.VOTE_NOT_ALLOWED
        if player not in self.voters():
            return T.VOTE_NOT_ALLOWED
        if user_id in self.votes:
            return T.VOTE_ALREADY
        if target_id == user_id:
            return T.VOTE_SELF

        target = self.players.get(target_id) if target_id else None
        if target_id and (not target or not target.alive):
            return "Эта цель недоступна."

        self.votes[user_id] = target_id
        if len(self.votes) >= len(self.voters()):
            self._vote_done.set()
        return T.VOTE_ACCEPTED.format(name=target.name if target else "воздержался")

    async def activate_item(self, user_id: int, item_key: str) -> str:
        player = self.players.get(user_id)
        if not player:
            return T.NOT_IN_GAME

        if item_key == "knife":
            if player.team is Team.MAFIA:
                return T.KNIFE_NOT_FOR_MAFIA
            if player.has_knife:
                return "🔪 Нож уже с вами."
            if not await db.consume_item(user_id, "knife"):
                return T.ITEM_GONE
            player.has_knife = True
            await self.dm(user_id, T.KNIFE_ACTIVATED, reply_markup=kb.knife_kb(self.chat_id))
            return T.KNIFE_ACTIVATED

        if item_key == "cover":
            if player.team is not Team.MAFIA:
                return T.COVER_ONLY_MAFIA
            if player.has_cover:
                return "🎭 Прикрытие уже активно."
            if not await db.consume_item(user_id, "cover"):
                return T.ITEM_GONE
            player.has_cover = True
            return T.COVER_ACTIVATED

        if item_key == "ghost_vote":
            if player.team is Team.MAFIA:
                return T.GHOST_VOTE_NOT_FOR_MAFIA
            if player.alive:
                return "👻 Предмет пригодится, только когда вас не станет."
            if player.death_reason not in ("mafia", "vote"):
                return T.GHOST_VOTE_NOT_FOR_MAFIA
            if player.ghost_vote:
                return "👻 Уже активно."
            if not await db.consume_item(user_id, "ghost_vote"):
                return T.ITEM_GONE
            player.ghost_vote = True
            return T.GHOST_VOTE_ACTIVATED

        return T.ITEM_GONE

    # ------------------------------------------------------------------ #
    #                          победа и завершение                        #
    # ------------------------------------------------------------------ #
    def _is_over(self) -> bool:
        return self._winner_now() is not None

    def _winner_now(self) -> Team | None:
        mafia = len(self.alive_of(Team.MAFIA))
        maniac = len(self.alive_of(Team.MANIAC))
        civil = len(self.alive_of(Team.CIVILIAN))
        total = mafia + maniac + civil

        if total == 0:
            return Team.CIVILIAN
        if mafia == 0 and maniac == 0:
            return Team.CIVILIAN
        if maniac and total == 1:
            return Team.MANIAC
        if mafia and mafia >= total - mafia and maniac == 0:
            return Team.MAFIA
        return None

    async def _check_win(self) -> bool:
        winner = self._winner_now()
        if winner is None:
            return False
        self.winner = winner
        self.phase = Phase.FINISHED
        return True

    async def _finish(self) -> None:
        self.phase = Phase.FINISHED
        await self.unpin_all()

        win_text = {
            Team.CIVILIAN: T.WIN_CIVILIANS,
            Team.MAFIA: T.WIN_MAFIA,
            Team.MANIAC: T.WIN_MANIAC,
        }.get(self.winner, "🏁 Игра окончена.")

        role_lines = [
            f"{'💀' if not p.alive else '🫀'} {p.mention} — {p.role.title}"
            for p in self.players.values()
        ]

        rewards: list[str] = []
        for player in self.players.values():
            won = self.winner is not None and player.team is self.winner
            coins = await db.register_result(player.user_id, won)
            if coins:
                rewards.append(f"{player.mention} +{coins} {CURRENCY}")

        await self.send(T.game_over(win_text, role_lines, rewards))

    async def stop(self, reason: str = T.GAME_STOPPED) -> None:
        self.phase = Phase.FINISHED
        self._interrupt.set()
        self._reg_done.set()
        self._night_done.set()
        self._vote_done.set()
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.unpin_all()
        await self.send(reason)


# --------------------------------------------------------------------------- #
#                                  Менеджер                                    #
# --------------------------------------------------------------------------- #
class GameManager:
    def __init__(self) -> None:
        self.games: dict[int, Game] = {}

    def get(self, chat_id: int) -> Game | None:
        return self.games.get(chat_id)

    def is_running(self, chat_id: int) -> bool:
        game = self.games.get(chat_id)
        return bool(game and game.phase is not Phase.FINISHED)

    def create(self, bot: Bot, chat_id: int, chat_title: str, bot_username: str) -> Game:
        game = Game(bot, chat_id, chat_title, bot_username)
        self.games[chat_id] = game
        game.task = asyncio.create_task(self._run(game))
        return game

    async def _run(self, game: Game) -> None:
        try:
            await game.run()
        finally:
            if self.games.get(game.chat_id) is game:
                self.games.pop(game.chat_id, None)

    def find_by_user(self, user_id: int) -> Game | None:
        for game in self.games.values():
            if user_id in game.players and game.phase is not Phase.FINISHED:
                return game
        return None

    async def stop(self, chat_id: int, reason: str = T.GAME_STOPPED) -> bool:
        game = self.games.pop(chat_id, None)
        if not game:
            return False
        await game.stop(reason)
        return True


manager = GameManager()
