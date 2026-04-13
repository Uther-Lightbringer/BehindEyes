"""
路由模块
"""
from .auth import router as auth_router
from .novels import router as novels_router
from .generate import router as generate_router
from .game import router as game_router
from .admin import router as admin_router
from .llm import router as llm_router
from .settings import router as settings_router

__all__ = [
    "auth_router",
    "novels_router",
    "generate_router",
    "game_router",
    "admin_router",
    "llm_router",
    "settings_router",
]
