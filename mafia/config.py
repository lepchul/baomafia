import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_PATH: str = os.getenv("DB_PATH", "baomafia.db")

# --- Тайминги (секунды) ---
REGISTRATION_TIME: int = _int("REGISTRATION_TIME", 90)
NIGHT_TIME: int = _int("NIGHT_TIME", 60)
DAY_TIME: int = _int("DAY_TIME", 90)
VOTE_TIME: int = _int("VOTE_TIME", 45)

# --- Правила ---
MIN_PLAYERS: int = 4
MAX_PLAYERS: int = 30
MAYOR_FROM: int = 15          # с этого количества игроков мэр обязателен

# --- Экономика ---
CURRENCY: str = "💎"
WIN_REWARD_MIN: int = 10
WIN_REWARD_MAX: int = 15

# Товары магазина: key -> (название, цена, описание)
SHOP_ITEMS: dict[str, dict] = {
    "knife": {
        "title": "Нож",
        "price": 100,
        "emoji": "🔪",
        "description": (
            "С ним ты можешь убить абсолютно любого в любое время, "
            "за раунд можно использовать 1 раз, "
            "когда ты мафия данный предмет использовать нельзя"
        ),
    },
    "cover": {
        "title": "Прикрытие",
        "price": 120,
        "emoji": "🎭",
        "description": (
            "Когда вас проверяет комиссар то показывает что вы мирный, "
            "предмет работает только во время того когда вы мафия"
        ),
    },
    "ghost_vote": {
        "title": "Голосование за умершего",
        "price": 50,
        "emoji": "👻",
        "description": (
            "Вы можете голосовать за кого либо даже когда вы мертвы, "
            "не работает на мафию."
        ),
    },
}
