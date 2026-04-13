"""
认证相关 API
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from auth import register_user, login_user, logout_user, get_current_user

router = APIRouter(prefix="/api/auth", tags=["认证"])


class AuthRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def api_register(req: AuthRequest):
    """用户注册"""
    if not req.username or len(req.username) < 2:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(req.password) < 4:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="密码至少 4 个字符")
    return await register_user(req.username, req.password)


@router.post("/login")
async def api_login(req: AuthRequest):
    """用户登录"""
    return await login_user(req.username, req.password)


@router.post("/logout")
async def api_logout(request: Request):
    """用户登出"""
    return await logout_user(request)


@router.get("/me")
async def api_me(request: Request):
    """获取当前用户信息"""
    user = get_current_user(request)
    if not user:
        return {"logged_in": False}
    return {"logged_in": True, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}
