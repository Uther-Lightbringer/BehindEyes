"""
认证模块：Session-based Cookie 鉴权
"""

import os
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse

from db import db

SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")
SESSION_COOKIE_NAME = "vn_session_token"
COOKIE_MAX_AGE = 24 * 60 * 60  # 24 小时


def sign_token(session_id: str) -> str:
    """生成带签名的 token: session_id.signature"""
    sig = hmac.new(SESSION_SECRET.encode(), session_id.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{session_id}.{sig}"


def verify_token(token: str) -> Optional[str]:
    """验证签名 token，返回 session_id"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        session_id, sig = parts
        expected = hmac.new(SESSION_SECRET.encode(), session_id.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return session_id
    except Exception:
        return None


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """从 cookie 中获取当前用户"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    session_id = verify_token(token)
    if not session_id:
        return None
    user = db.get_session_user(session_id)
    return user


async def login_required(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """依赖注入：要求用户已登录"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def admin_required(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """依赖注入：要求管理员权限"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """同步获取当前用户（用于中间件/工具函数）"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    session_id = verify_token(token)
    if not session_id:
        return None
    return db.get_session_user(session_id)


async def register_user(username: str, password: str) -> Response:
    """注册用户，登录成功返回带 session 的响应"""
    from passlib.hash import bcrypt

    user = db.get_user_by_username(username)
    if user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user_id = str(uuid.uuid4())
    password_hash = bcrypt.hash(password)
    created = db.create_user(user_id, username, password_hash)
    if not created:
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    # 创建 session
    session_id = str(uuid.uuid4())
    db.create_session(session_id, user_id)
    token = sign_token(session_id)

    response = JSONResponse({
        "success": True,
        "user": {"id": created["id"], "username": created["username"], "role": created["role"]}
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        path="/",
    )
    return response


async def login_user(username: str, password: str) -> Response:
    """用户登录"""
    from passlib.hash import bcrypt

    user = db.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not bcrypt.verify(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 创建 session
    session_id = str(uuid.uuid4())
    db.create_session(session_id, user["id"])
    token = sign_token(session_id)

    response = JSONResponse({
        "success": True,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]}
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        path="/",
    )
    return response


async def logout_user(request: Request) -> Response:
    """登出"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        session_id = verify_token(token)
        if session_id:
            db.delete_session(session_id)

    response = JSONResponse({"success": True, "message": "已退出登录"})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response
