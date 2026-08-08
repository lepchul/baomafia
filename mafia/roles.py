"""Роли Баограда и раздача их игрокам."""

import random
from dataclasses import dataclass
from enum import Enum

from .config import MAYOR_FROM


class Team(str, Enum):
    CIVILIAN = "civilian"
    MAFIA = "mafia"
    MANIAC = "maniac"


@dataclass(frozen=True)
class Role:
    key: str
    name: str
    emoji: str
    team: Team
    description: str
    night_action: bool = False
    #: подсказка, которая приходит в личку ночью
    night_prompt: str = ""

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


ROLES: dict[str, Role] = {
    # ------------------------------- мирные -------------------------------- #
    "civilian": Role(
        key="civilian",
        name="Мирный",
        emoji="🐱",
        team=Team.CIVILIAN,
        description="Ты просто пытаешься вычислить мафию на дневном голосовании.",
    ),
    "commissar": Role(
        key="commissar",
        name="Комиссар Каттани",
        emoji="🕵️",
        team=Team.CIVILIAN,
        description=(
            "Ты — главная надежда мирных, ты можешь либо убить либо проверить кого то "
            "на мафию, учти, что бывают поддельные документы."
        ),
        night_action=True,
        night_prompt="🕵️ Кем займёшься этой ночью, комиссар?",
    ),
    "doctor": Role(
        key="doctor",
        name="Доктор",
        emoji="🩺",
        team=Team.CIVILIAN,
        description="Твоя задача вылечить кого либо да бы защитить его от мафии.",
        night_action=True,
        night_prompt="🩺 Кого будешь лечить этой ночью?",
    ),
    "lover": Role(
        key="lover",
        name="Любовница",
        emoji="💋",
        team=Team.CIVILIAN,
        description=(
            "Ты можешь придти к кому либо ночью, если его убьет мафия то и тебя тоже."
        ),
        night_action=True,
        night_prompt="💋 К кому пойдёшь этой ночью?",
    ),
    "kamikaze": Role(
        key="kamikaze",
        name="Камикадзе",
        emoji="💣",
        team=Team.CIVILIAN,
        description=(
            "Если тебя убьет мафия либо Комиссар, то они умрут вместе с тобой "
            "(умрет из мафии только кто то один)."
        ),
    ),
    "mayor": Role(
        key="mayor",
        name="Мэр",
        emoji="🎖",
        team=Team.CIVILIAN,
        description=(
            "Ты мэр Баограда, от твоего голоса на голосовании зависит все, не промахнись! "
            "Твой голос считается за два и решает спорные ситуации."
        ),
    ),
    "journalist": Role(
        key="journalist",
        name="Журналист",
        emoji="📰",
        team=Team.CIVILIAN,
        description=(
            "Ты пишешь для «Баоградского вестника». Ночью выбираешь двоих — и узнаёшь, "
            "в одной ли они команде. Имён в статье не будет, только факт."
        ),
        night_action=True,
        night_prompt="📰 Выбери первого героя ночного репортажа:",
    ),
    "sergeant": Role(
        key="sergeant",
        name="Сержант",
        emoji="🚔",
        team=Team.CIVILIAN,
        description=(
            "Ты стажёр Каттани. Пока комиссар жив — ты обычный житель, но если его "
            "не станет, ты получишь значок и все его возможности."
        ),
    ),
    "granny": Role(
        key="granny",
        name="Бабуля с окна",
        emoji="👵",
        team=Team.CIVILIAN,
        description=(
            "Ты целыми днями сидишь у окна и всё видишь. Ночью выбираешь дом и узнаёшь, "
            "сколько котов туда наведалось."
        ),
        night_action=True,
        night_prompt="👵 За чьим двором понаблюдаешь этой ночью?",
    ),
    # ------------------------------- мафия --------------------------------- #
    "mafia": Role(
        key="mafia",
        name="Мафия",
        emoji="🕶",
        team=Team.MAFIA,
        description="Ты — помощник Дона, пытайся максимально не палится.",
        night_action=True,
        night_prompt="🕶 Кого убираем этой ночью?",
    ),
    "don": Role(
        key="don",
        name="Дон",
        emoji="🎩",
        team=Team.MAFIA,
        description=(
            "Ты — глава мафии, тебя все ищут, попытайся не дать найти себя. "
            "В спорной ситуации последнее слово за тобой."
        ),
        night_action=True,
        night_prompt="🎩 Кого убираем этой ночью, дон?",
    ),
    # ------------------------------ одиночки ------------------------------- #
    "maniac": Role(
        key="maniac",
        name="Маньяк",
        emoji="🔪",
        team=Team.MANIAC,
        description=(
            "Ты не относишься к мафии однако тоже можешь убивать, достаточно редкая роль. "
            "Побеждаешь, только если останешься последним котом Баограда."
        ),
        night_action=True,
        night_prompt="🔪 Кого навестишь этой ночью?",
    ),
}


def get(key: str) -> Role:
    return ROLES[key]


def _mafia_count(players: int) -> int:
    if players <= 6:
        return 1
    if players <= 9:
        return 2
    if players <= 13:
        return 3
    if players <= 17:
        return 4
    return players // 4


#: редкие роли: key -> (минимум игроков, шанс появления)
RARE_ROLES: dict[str, tuple[int, float]] = {
    "kamikaze": (7, 0.25),
    "lover": (8, 0.30),
    "granny": (9, 0.20),
    "maniac": (9, 0.20),
    "journalist": (10, 0.25),
    "sergeant": (12, 0.20),
}


def distribute(player_count: int) -> list[str]:
    """Возвращает перемешанный список ключей ролей на `player_count` игроков."""
    if player_count < 4:
        raise ValueError("минимум 4 игрока")

    roles: list[str] = []

    # 1. Мафия: первый всегда Дон.
    mafia_total = _mafia_count(player_count)
    roles.append("don")
    roles.extend(["mafia"] * (mafia_total - 1))

    # 2. Комиссар — всегда.
    roles.append("commissar")

    # 3. Доктор — с 5 игроков.
    if player_count >= 5:
        roles.append("doctor")

    # 4. Мэр — обязателен с 15 игроков и всегда ровно один.
    if player_count >= MAYOR_FROM:
        roles.append("mayor")

    # 5. Редкие роли — выпадают не всегда.
    #    Оставляем минимум одного чистого мирного.
    free_slots = player_count - len(roles) - 1
    for key, (minimum, chance) in RARE_ROLES.items():
        if free_slots <= 0:
            break
        if player_count < minimum:
            continue
        if random.random() > chance:
            continue
        if key == "sergeant" and "commissar" not in roles:
            continue
        roles.append(key)
        free_slots -= 1

    # 6. Остальные — мирные жители.
    roles.extend(["civilian"] * (player_count - len(roles)))
    random.shuffle(roles)
    return roles


def team_of(role_key: str) -> Team:
    return ROLES[role_key].team


def roles_overview() -> str:
    """Красивый список всех ролей — для кнопки «Роли»."""
    blocks = {
        Team.CIVILIAN: "<b>🏘 Мирный город</b>",
        Team.MAFIA: "<b>🕶 Мафия</b>",
        Team.MANIAC: "<b>🔪 Сам по себе</b>",
    }
    out: list[str] = []
    for team, header in blocks.items():
        out.append(header)
        for role in ROLES.values():
            if role.team is team:
                out.append(f"{role.title} — {role.description}")
        out.append("")
    return "\n".join(out).strip()
