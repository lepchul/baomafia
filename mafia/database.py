"""Слой работы с SQLite. Баланс Baocoin'ов, инвентарь и статистика."""

import random

import aiosqlite

from .config import DB_PATH, SHOP_ITEMS, WIN_REWARD_MAX, WIN_REWARD_MIN

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    full_name   TEXT    NOT NULL DEFAULT '',
    username    TEXT,
    balance     INTEGER NOT NULL DEFAULT 0,
    games       INTEGER NOT NULL DEFAULT 0,
    wins        INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id  INTEGER NOT NULL,
    item     TEXT    NOT NULL,
    amount   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item)
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def init() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


# --------------------------------------------------------------------------- #
#                                 Пользователи                                 #
# --------------------------------------------------------------------------- #
async def ensure_user(user_id: int, full_name: str = "", username: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, full_name, username) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name, "
            "username = excluded.username",
            (user_id, full_name, username),
        )
        await db.commit()


async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def add_balance(user_id: int, amount: int) -> int:
    """Меняет баланс и возвращает новое значение."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute(
            "UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?",
            (amount, user_id),
        )
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def get_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance, games, wins FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return {"balance": 0, "games": 0, "wins": 0}
    return {"balance": row[0], "games": row[1], "wins": row[2]}


async def register_result(user_id: int, won: bool) -> int:
    """Отмечает сыгранную игру. За победу начисляет 10-15 Baocoin'ов.

    Возвращает количество начисленных монет (0 при поражении).
    """
    reward = random.randint(WIN_REWARD_MIN, WIN_REWARD_MAX) if won else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute(
            "UPDATE users SET games = games + 1, wins = wins + ?, balance = balance + ? "
            "WHERE user_id = ?",
            (1 if won else 0, reward, user_id),
        )
        await db.commit()
    return reward


async def top_players(limit: int = 10) -> list[tuple[str, int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name, balance, wins FROM users ORDER BY balance DESC, wins DESC LIMIT ?",
            (limit,),
        ) as cur:
            return list(await cur.fetchall())


# --------------------------------------------------------------------------- #
#                                  Инвентарь                                   #
# --------------------------------------------------------------------------- #
async def get_inventory(user_id: int) -> dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT item, amount FROM inventory WHERE user_id = ? AND amount > 0", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
    return {item: amount for item, amount in rows}


async def get_item_amount(user_id: int, item: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM inventory WHERE user_id = ? AND item = ?", (user_id, item)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def buy_item(user_id: int, item: str) -> tuple[bool, str, int]:
    """Покупка предмета. -> (успех, текст-причина, новый баланс)."""
    meta = SHOP_ITEMS.get(item)
    if not meta:
        return False, "Такого товара нет.", await get_balance(user_id)

    price = meta["price"]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        balance = row[0] if row else 0

        if balance < price:
            return False, "not_enough", balance

        await db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id)
        )
        await db.execute(
            "INSERT INTO inventory (user_id, item, amount) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, item) DO UPDATE SET amount = amount + 1",
            (user_id, item),
        )
        await db.commit()
    return True, "ok", balance - price


async def consume_item(user_id: int, item: str) -> bool:
    """Списывает 1 штуку предмета. False, если предмета нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM inventory WHERE user_id = ? AND item = ?", (user_id, item)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[0] <= 0:
            return False
        await db.execute(
            "UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND item = ?",
            (user_id, item),
        )
        await db.commit()
    return True


# --------------------------------------------------------------------------- #
#                                     Чаты                                     #
# --------------------------------------------------------------------------- #
async def remember_chat(chat_id: int, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chats (chat_id, title) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title",
            (chat_id, title),
        )
        await db.commit()
