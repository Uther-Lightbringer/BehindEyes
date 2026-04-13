"""
用户设置 API
"""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional, Dict, Any

from db import db
from auth import get_current_user, login_required
from llm_client import PRESET_PROVIDERS

router = APIRouter(tags=["设置"])


@router.get("/api/settings")
async def get_user_settings_endpoint(request: Request):
    """获取当前用户的生成配置"""
    user = get_current_user(request)
    if not user:
        return {"chunk_size": 5000, "chunk_overlap": 300, "max_total_chars": 25000}
    settings = db.get_user_settings(user["id"])
    settings["max_total_chars"] = settings.get("chunk_size", 5000) * 5
    return settings


@router.post("/api/settings")
async def update_user_settings_endpoint(request: Request, body: Optional[Dict[str, Any]] = None):
    """更新当前用户的生成配置"""
    user = await login_required(get_current_user(request))
    if not body:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    chunk_size = body.get("chunk_size")
    chunk_overlap = body.get("chunk_overlap")
    llm_provider = body.get("llm_provider")
    llm_model = body.get("llm_model")
    custom_api_keys = body.get("custom_api_keys")
    image_api_key = body.get("image_api_key")

    if chunk_size is not None and (not isinstance(chunk_size, int) or chunk_size < 2000 or chunk_size > 10000):
        raise HTTPException(status_code=400, detail="分段字数需在 2000-10000 之间")
    if chunk_overlap is not None and (not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= 1000):
        raise HTTPException(status_code=400, detail="重叠字数需在 0-999 之间")
    if llm_provider is not None and llm_provider not in PRESET_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的 LLM 提供商: {llm_provider}")

    db.update_user_settings(
        user["id"],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        llm_provider=llm_provider,
        llm_model=llm_model,
        custom_api_keys=custom_api_keys,
        image_api_key=image_api_key
    )
    settings = db.get_user_settings(user["id"])
    settings["max_total_chars"] = settings.get("chunk_size", 5000) * 5
    return settings


@router.get("/api/art-styles")
async def get_art_styles():
    """获取支持的艺术风格列表"""
    from image_client import EvolinkImageClient
    image_client = EvolinkImageClient()
    return {"styles": image_client.get_supported_styles()}


@router.post("/api/novel/{novel_id}/art-style")
async def update_novel_art_style(novel_id: str, request: Request):
    """更新小说的艺术风格"""
    user = await login_required(get_current_user(request))

    novel_db = db.get_novel(novel_id)
    if not novel_db:
        raise HTTPException(status_code=404, detail="小说不存在")

    if user["role"] != "admin" and novel_db["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="无权修改")

    body = await request.json()
    art_style = body.get("art_style", "anime")
    style_keywords = body.get("style_keywords", "")

    if art_style not in ["anime", "realistic", "watercolor", "chinese_ink"]:
        raise HTTPException(status_code=400, detail="不支持的艺术风格")

    db.update_novel_art_style(novel_id, art_style, style_keywords)

    return {"success": True, "art_style": art_style, "style_keywords": style_keywords}


@router.post("/api/image/test")
async def test_image_connection(request: Request):
    """测试图片生成 API 连接"""
    import aiohttp
    import os

    body = await request.json()
    api_key = body.get("api_key") or os.getenv("EVOLINK_API_KEY")
    if not api_key:
        return {"success": False, "error": "API Key 未配置"}

    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "z-image-turbo", "prompt": "一只可爱的小猫，简单素描", "size": "1:1"}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.evolink.ai/v1/images/generations",
                headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status in [200, 201]:
                    task_info = await resp.json()
                    return {"success": True, "message": f"连接成功", "task_id": task_info.get("id")}
                else:
                    return {"success": False, "error": f"API 返回错误 ({resp.status})"}

    except Exception as e:
        return {"success": False, "error": str(e)}
