"""
错误处理中间件
统一处理所有异常，返回标准格式
"""
import logging
import traceback
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .exceptions import AppException
from .error_codes import ErrorCode, ERROR_MESSAGES
from .request_id import get_request_id

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """统一错误处理中间件"""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except AppException as e:
            return self._handle_app_exception(request, e)
        except HTTPException as e:
            return self._handle_http_exception(request, e)
        except RequestValidationError as e:
            return self._handle_validation_error(request, e)
        except Exception as e:
            return self._handle_unknown_error(request, e)

    def _handle_app_exception(self, request: Request, exc: AppException) -> JSONResponse:
        """处理应用异常"""
        request_id = get_request_id(request)
        response = exc.to_dict()
        response["error"]["request_id"] = request_id

        logger.warning(
            f"AppException: {exc.code} - {exc.message}",
            extra={"request_id": request_id, "detail": exc.detail}
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=response
        )

    def _handle_http_exception(self, request: Request, exc: HTTPException) -> JSONResponse:
        """处理 HTTP 异常"""
        request_id = get_request_id(request)

        # 映射 HTTP 状态码到错误代码
        code_map = {
            400: ErrorCode.INVALID_REQUEST,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            500: ErrorCode.UNKNOWN_ERROR,
        }

        code = code_map.get(exc.status_code, ErrorCode.UNKNOWN_ERROR)
        message = str(exc.detail) if exc.detail else ERROR_MESSAGES.get(code, "未知错误")

        response = {
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id
            }
        }

        logger.warning(
            f"HTTPException: {exc.status_code} - {message}",
            extra={"request_id": request_id}
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=response
        )

    def _handle_validation_error(self, request: Request, exc: RequestValidationError) -> JSONResponse:
        """处理参数验证错误"""
        request_id = get_request_id(request)

        # 提取验证错误详情
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error.get("loc", [])),
                "message": error.get("msg", "验证失败"),
                "type": error.get("type", "validation_error")
            })

        response = {
            "success": False,
            "error": {
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "参数验证失败",
                "detail": errors,
                "request_id": request_id
            }
        }

        logger.warning(
            f"ValidationError: {errors}",
            extra={"request_id": request_id}
        )

        return JSONResponse(
            status_code=400,
            content=response
        )

    def _handle_unknown_error(self, request: Request, exc: Exception) -> JSONResponse:
        """处理未知错误"""
        request_id = get_request_id(request)

        # 记录详细错误日志
        logger.error(
            f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
            extra={
                "request_id": request_id,
                "traceback": traceback.format_exc()
            }
        )

        response = {
            "success": False,
            "error": {
                "code": ErrorCode.UNKNOWN_ERROR,
                "message": "服务器内部错误",
                "request_id": request_id
            }
        }

        return JSONResponse(
            status_code=500,
            content=response
        )


def setup_exception_handlers(app):
    """注册异常处理器到 FastAPI 应用"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        request_id = get_request_id(request)
        response = exc.to_dict()
        response["error"]["request_id"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content=response
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = get_request_id(request)
        code_map = {
            400: ErrorCode.INVALID_REQUEST,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            500: ErrorCode.UNKNOWN_ERROR,
        }
        code = code_map.get(exc.status_code, ErrorCode.UNKNOWN_ERROR)
        message = str(exc.detail) if exc.detail else ERROR_MESSAGES.get(code, "未知错误")

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = get_request_id(request)
        errors = [{"field": ".".join(str(loc) for loc in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]

        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR,
                    "message": "参数验证失败",
                    "detail": errors,
                    "request_id": request_id
                }
            }
        )
