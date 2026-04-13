"""
LLM 提供商 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from llm_client import LLMClient, PRESET_PROVIDERS

router = APIRouter(prefix="/api/llm", tags=["LLM"])


@router.get("/providers")
async def get_llm_providers():
    """获取所有支持的 LLM 提供商列表"""
    return LLMClient.get_available_providers()


@router.get("/providers/{provider_id}/models")
async def get_llm_provider_models(provider_id: str):
    """获取指定提供商支持的模型列表"""
    models = LLMClient.get_provider_models(provider_id)
    if not models:
        return {"error": "未知的提供商", "provider_id": provider_id}
    return {"provider_id": provider_id, "models": models}


class LLMTestRequest(BaseModel):
    provider_id: str
    model: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/test")
async def test_llm_connection(request: LLMTestRequest):
    """测试 LLM 连接是否正常"""
    try:
        client = LLMClient(
            provider_id=request.provider_id,
            model=request.model,
            custom_api_key=request.api_key
        )

        if not client.is_configured():
            return {
                "success": False,
                "error": "API Key 未配置，请输入 API Key 或设置环境变量"
            }

        response = await client.chat(
            messages=[{"role": "user", "content": "你好，请回复'测试成功'四个字"}],
            max_tokens=50,
            temperature=0.1
        )

        if response and len(response.strip()) > 0:
            return {
                "success": True,
                "message": f"连接成功！模型响应: {response[:100]}",
                "provider": request.provider_id,
                "model": client.model
            }
        else:
            return {"success": False, "error": "模型返回空响应"}

    except Exception as e:
        return {"success": False, "error": str(e)}
