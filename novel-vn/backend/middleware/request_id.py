"""
请求 ID 中间件
用于追踪请求和错误日志
"""
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成唯一 ID"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 生成请求 ID
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"

        # 存储到请求状态
        request.state.request_id = request_id

        # 执行请求
        response = await call_next(request)

        # 添加到响应头
        response.headers["X-Request-ID"] = request_id

        return response


def get_request_id(request: Request) -> str:
    """获取当前请求 ID"""
    return getattr(request.state, "request_id", "unknown")
