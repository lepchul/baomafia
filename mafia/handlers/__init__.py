from aiogram import Router

from . import game_cb, group, moderation, private


def setup_routers() -> Router:
    """Порядок важен: модерация подключается последней."""
    router = Router(name="root")
    router.include_router(private.router)
    router.include_router(group.router)
    router.include_router(game_cb.router)
    router.include_router(moderation.router)
    return router
