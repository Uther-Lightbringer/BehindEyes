"""
LLM 统一客户端
使用 litellm 统一调用不同大模型 API
支持：DeepSeek、OpenAI、MiniMax、Qwen 等
"""

import os
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import litellm
from litellm import completion


@dataclass
class LLMProvider:
    """大模型提供商配置"""
    id: str
    name: str
    display_name: str
    api_base_env: str  # 环境变量名
    default_model: str
    models: List[str]
    api_base: str = ""  # API 端点


# 预设的提供商配置
PRESET_PROVIDERS = {
    "deepseek": LLMProvider(
        id="deepseek",
        name="deepseek",
        display_name="DeepSeek",
        api_base_env="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-coder"],
        api_base="https://api.deepseek.com"
    ),
    "openai": LLMProvider(
        id="openai",
        name="openai",
        display_name="OpenAI",
        api_base_env="OPENAI_API_KEY",
        default_model="gpt-3.5-turbo",
        models=["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o"],
        api_base="https://api.openai.com/v1"
    ),
    "minimax": LLMProvider(
        id="minimax",
        name="minimax",
        display_name="MiniMax",
        api_base_env="MINIMAX_API_KEY",
        default_model="abab6.5s-chat",
        models=["abab6.5s-chat", "abab6.5g-chat", "abab5.5-chat"],
        api_base="https://api.minimax.chat/v1"
    ),
    "qwen": LLMProvider(
        id="qwen",
        name="qwen",
        display_name="通义千问",
        api_base_env="QWEN_API_KEY",
        default_model="qwen-turbo",
        models=["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext"],
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1"
    ),
    "zhipu": LLMProvider(
        id="zhipu",
        name="zhipu",
        display_name="智谱AI",
        api_base_env="ZHIPU_API_KEY",
        default_model="glm-4",
        models=["glm-4", "glm-4-flash", "glm-3-turbo"],
        api_base="https://open.bigmodel.cn/api/paas/v4"
    ),
}


class LLMClient:
    """统一大模型客户端"""

    def __init__(self, provider_id: str = "deepseek", model: str = None,
                 custom_api_key: str = None):
        """
        初始化 LLM 客户端

        Args:
            provider_id: 提供商 ID (deepseek, openai, qwen 等)
            model: 模型名称，不指定则使用默认模型
            custom_api_key: 用户自定义的 API Key，不指定则从环境变量读取
        """
        self.provider_id = provider_id
        self.provider = PRESET_PROVIDERS.get(provider_id, PRESET_PROVIDERS["deepseek"])
        self.model = model or self.provider.default_model
        self.custom_api_key = custom_api_key

        # 设置 litellm 参数
        self._setup_litellm()

    def _setup_litellm(self):
        """配置 litellm"""
        # 获取 API Key
        api_key = self.custom_api_key or os.getenv(self.provider.api_base_env)

        if not api_key:
            print(f"警告: {self.provider.api_base_env} 环境变量未设置")

        # 设置 API Key 到环境变量（litellm 会自动读取）
        os.environ[self.provider.api_base_env] = api_key or ""

        # litellm 配置
        litellm.drop_params = True  # 自动丢弃不支持的参数
        litellm.set_verbose = False  # 关闭详细日志

    def _get_model_string(self) -> str:
        """获取 litellm 格式的模型字符串"""
        # litellm 使用 "provider/model" 格式
        provider_prefix = self.provider.name
        return f"{provider_prefix}/{self.model}"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        response_format: Dict = None,
        **kwargs
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            response_format: 响应格式 {"type": "json_object"}
            **kwargs: 其他参数

        Returns:
            模型响应文本
        """
        # 构建消息列表
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # 构建请求参数
        params = {
            "model": self._get_model_string(),
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # 添加响应格式（如果支持）
        if response_format:
            params["response_format"] = response_format

        # 添加其他参数
        params.update(kwargs)

        try:
            # 调用 litellm
            response = await litellm.acompletion(**params)

            # 提取响应文本
            return response.choices[0].message.content

        except Exception as e:
            print(f"LLM 调用失败: {e}")
            raise

    async def chat_with_json_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        temperature: float = 0.3,
        max_tokens: int = 6000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送聊天请求并期望 JSON 响应

        Args:
            messages: 消息列表
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            解析后的 JSON 对象
        """
        response = await self.chat(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            **kwargs
        )

        # 解析 JSON
        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析 JSON 响应"""
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
                return json.loads(json_str.strip())
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
                return json.loads(json_str.strip())
            else:
                # 尝试找到 JSON 对象
                start = response.find("{")
                end = response.rfind("}") + 1
                if start != -1 and end > start:
                    return json.loads(response[start:end])
                raise ValueError(f"无法解析 JSON 响应: {response[:200]}")

    def is_configured(self) -> bool:
        """检查是否已配置 API Key"""
        api_key = self.custom_api_key or os.getenv(self.provider.api_base_env)
        return bool(api_key)

    @staticmethod
    def get_available_providers() -> List[Dict[str, Any]]:
        """获取所有可用的提供商列表"""
        result = []
        for provider_id, provider in PRESET_PROVIDERS.items():
            has_key = bool(os.getenv(provider.api_base_env))
            result.append({
                "id": provider.id,
                "name": provider.name,
                "display_name": provider.display_name,
                "models": provider.models,
                "default_model": provider.default_model,
                "has_api_key": has_key,
                "is_configured": has_key
            })
        return result

    @staticmethod
    def get_provider_models(provider_id: str) -> List[str]:
        """获取指定提供商的模型列表"""
        provider = PRESET_PROVIDERS.get(provider_id)
        if provider:
            return provider.models
        return []


# 便捷函数
async def call_llm(
    prompt: str,
    system_prompt: str = None,
    provider: str = "deepseek",
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 4000,
    custom_api_key: str = None
) -> str:
    """
    便捷的 LLM 调用函数

    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词
        provider: 提供商 ID
        model: 模型名称
        temperature: 温度
        max_tokens: 最大 token
        custom_api_key: 自定义 API Key

    Returns:
        模型响应
    """
    client = LLMClient(
        provider_id=provider,
        model=model,
        custom_api_key=custom_api_key
    )
    return await client.chat(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )
