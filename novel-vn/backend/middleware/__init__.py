"""
中间件模块
提供统一错误处理和请求追踪
"""
from .error_codes import ErrorCode, ERROR_MESSAGES
from .exceptions import (
    AppException,
    NotFoundException,
    UnauthorizedException,
    ForbiddenException,
    ValidationException,
    BusinessException,
    novel_not_found,
    chapter_not_found,
    character_not_found,
    task_not_found,
    login_required,
    forbidden,
    admin_required,
    validation_error,
)
from .error_handler import ErrorHandlerMiddleware, setup_exception_handlers
from .request_id import RequestIDMiddleware, get_request_id

__all__ = [
    # 错误代码
    "ErrorCode",
    "ERROR_MESSAGES",
    # 异常类
    "AppException",
    "NotFoundException",
    "UnauthorizedException",
    "ForbiddenException",
    "ValidationException",
    "BusinessException",
    # 便捷方法
    "novel_not_found",
    "chapter_not_found",
    "character_not_found",
    "task_not_found",
    "login_required",
    "forbidden",
    "admin_required",
    "validation_error",
    # 中间件
    "ErrorHandlerMiddleware",
    "RequestIDMiddleware",
    "get_request_id",
    "setup_exception_handlers",
]
