"""
自定义异常类
"""
from typing import Optional, Any
from .error_codes import ErrorCode, ERROR_MESSAGES


class AppException(Exception):
    """应用异常基类"""

    def __init__(
        self,
        code: str = ErrorCode.UNKNOWN_ERROR,
        message: Optional[str] = None,
        detail: Optional[Any] = None,
        status_code: int = 400
    ):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "未知错误")
        self.detail = detail
        self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        result = {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.detail is not None:
            result["error"]["detail"] = self.detail
        return result


class NotFoundException(AppException):
    """资源不存在异常"""

    def __init__(
        self,
        code: str = ErrorCode.NOT_FOUND,
        message: Optional[str] = None,
        detail: Optional[Any] = None
    ):
        super().__init__(code=code, message=message, detail=detail, status_code=404)


class UnauthorizedException(AppException):
    """未授权异常"""

    def __init__(
        self,
        code: str = ErrorCode.UNAUTHORIZED,
        message: Optional[str] = None,
        detail: Optional[Any] = None
    ):
        super().__init__(code=code, message=message, detail=detail, status_code=401)


class ForbiddenException(AppException):
    """权限不足异常"""

    def __init__(
        self,
        code: str = ErrorCode.FORBIDDEN,
        message: Optional[str] = None,
        detail: Optional[Any] = None
    ):
        super().__init__(code=code, message=message, detail=detail, status_code=403)


class ValidationException(AppException):
    """参数验证异常"""

    def __init__(
        self,
        code: str = ErrorCode.VALIDATION_ERROR,
        message: Optional[str] = None,
        detail: Optional[Any] = None
    ):
        super().__init__(code=code, message=message, detail=detail, status_code=400)


class BusinessException(AppException):
    """业务逻辑异常"""

    def __init__(
        self,
        code: str = ErrorCode.UNKNOWN_ERROR,
        message: Optional[str] = None,
        detail: Optional[Any] = None,
        status_code: int = 400
    ):
        super().__init__(code=code, message=message, detail=detail, status_code=status_code)


# 便捷工厂方法
def novel_not_found(novel_id: str = None) -> NotFoundException:
    detail = {"novel_id": novel_id} if novel_id else None
    return NotFoundException(code=ErrorCode.NOVEL_NOT_FOUND, detail=detail)


def chapter_not_found(chapter_index: int = None) -> NotFoundException:
    detail = {"chapter_index": chapter_index} if chapter_index is not None else None
    return NotFoundException(code=ErrorCode.CHAPTER_NOT_FOUND, detail=detail)


def character_not_found(character_id: str = None) -> NotFoundException:
    detail = {"character_id": character_id} if character_id else None
    return NotFoundException(code=ErrorCode.CHARACTER_NOT_FOUND, detail=detail)


def task_not_found(task_id: str = None) -> NotFoundException:
    detail = {"task_id": task_id} if task_id else None
    return NotFoundException(code=ErrorCode.TASK_NOT_FOUND, detail=detail)


def login_required() -> UnauthorizedException:
    return UnauthorizedException(code=ErrorCode.LOGIN_REQUIRED, message="请先登录")


def forbidden(message: str = "无权访问") -> ForbiddenException:
    return ForbiddenException(message=message)


def admin_required() -> ForbiddenException:
    return ForbiddenException(code=ErrorCode.ADMIN_REQUIRED, message="需要管理员权限")


def validation_error(message: str, detail: Any = None) -> ValidationException:
    return ValidationException(message=message, detail=detail)
