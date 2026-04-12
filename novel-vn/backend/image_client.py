"""
图片生成客户端
支持多种艺术风格，生成角色头像和场景背景
"""

import os
import asyncio
import aiohttp
from typing import Optional, Dict, Any


# ============================================================
# 风格定义
# ============================================================
ART_STYLES = {
    "anime": {
        "name": "动漫风格",
        "positive": "anime style, 2D illustration, cel shading, vibrant colors, high quality anime art",
        "negative": "realistic, photo, 3D, photorealistic",
    },
    "realistic": {
        "name": "真实写真",
        "positive": "photorealistic, realistic photography, high detail, professional portrait photo, soft lighting, 8K quality",
        "negative": "anime, cartoon, illustration, 2D, drawing, sketch",
    },
    "watercolor": {
        "name": "水彩插画",
        "positive": "watercolor painting style, soft colors, artistic illustration, delicate brushstrokes, dreamy atmosphere",
        "negative": "photorealistic, sharp lines, digital art, anime",
    },
    "chinese_ink": {
        "name": "古风水墨",
        "positive": "Chinese ink painting style, traditional oriental art, elegant brushwork, minimalist, classical aesthetic",
        "negative": "photorealistic, western style, modern, bright colors",
    },
}

# 通用负面提示词
COMMON_NEGATIVE_PROMPT = """
nsfw, low quality, worst quality, bad anatomy, bad hands,
missing fingers, extra digits, fewer digits, cropped,
worst face, low quality face, bad face, extra limbs,
text, watermark, signature, blurry, deformed, ugly,
disfigured, mutation, mutated, gross, disgusting
"""

# 性格到表情的映射
PERSONALITY_TO_EXPRESSION = {
    "活泼": "cheerful expression, bright smile",
    "开朗": "happy expression, warm smile",
    "冷酷": "cold expression, stern face",
    "温柔": "gentle expression, soft smile",
    "勇敢": "confident expression, determined look",
    "阴险": "sly expression, cunning smile",
    "傲娇": "tsundere expression, slightly annoyed look",
    "高冷": "aloof expression, cool demeanor",
    "热情": "enthusiastic expression, bright eyes",
    "忧郁": "melancholic expression, sad eyes",
    "邪恶": "sinister expression, menacing look",
    "可爱": "cute expression, innocent look",
    "沉稳": "calm expression, composed face",
    "霸气": "domineering expression, fierce look",
    "腹黑": "subtle cunning expression, hidden smile",
}


class EvolinkImageClient:
    API_BASE = "https://api.evolink.ai"

    def __init__(self):
        api_key = os.getenv("EVOLINK_API_KEY")
        if not api_key:
            print("警告: EVOLINK_API_KEY 环境变量未设置")
            self.api_key = None
        else:
            self.api_key = api_key

    def is_configured(self) -> bool:
        return self.api_key is not None

    def get_supported_styles(self) -> Dict[str, str]:
        """获取支持的风格列表"""
        return {k: v["name"] for k, v in ART_STYLES.items()}

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        size: str = "1:1",
        timeout: int = 120,
    ) -> Optional[str]:
        """生成图片并返回 URL"""
        if not self.api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "z-image-turbo",
            "prompt": prompt,
            "size": size,
        }

        # 如果 API 支持负面提示词
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            # 1. 提交图片生成任务
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE}/v1/images/generations",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"提交图片生成任务失败: {resp.status} - {error_text}")
                        return None
                    task_info = await resp.json()

            task_id = task_info.get("id")
            if not task_id:
                print("未获取到图片任务ID")
                return None

            # 2. 轮询任务状态
            poll_interval = 2
            elapsed = 0
            async with aiohttp.ClientSession() as session:
                while elapsed < timeout:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    async with session.get(
                        f"{self.API_BASE}/v1/tasks/{task_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        detail = await resp.json()

                    status = detail.get("status")
                    if status == "completed":
                        results = detail.get("results", [])
                        if results:
                            return results[0]
                        return None
                    elif status == "failed":
                        error = detail.get("error", {})
                        print(f"图片生成失败: {error.get('message', 'unknown')}")
                        return None

            print("图片生成超时")
            return None

        except Exception as e:
            print(f"图片生成异常: {e}")
            return None

    @staticmethod
    def build_avatar_prompt(
        char: Dict[str, Any],
        art_style: str = "anime",
        style_keywords: str = "",
    ) -> tuple[str, str]:
        """
        构建角色头像提示词

        Args:
            char: 角色信息字典，包含 name, gender, age_range, appearance 等
            art_style: 艺术风格 (anime/realistic/watercolor/chinese_ink)
            style_keywords: 额外的风格关键词

        Returns:
            tuple: (正面提示词, 负面提示词)
        """
        # 获取风格配置
        style_config = ART_STYLES.get(art_style, ART_STYLES["anime"])

        # 构建各部分描述
        parts = []

        # === 基础风格 ===
        parts.append(style_config["positive"])

        # === 角色基础信息 ===
        name = char.get("name", "character")
        gender = char.get("gender", "")
        age_range = char.get("age_range", "")

        # 性别和年龄
        if gender:
            gender_en = "male" if gender == "男" else "female" if gender == "女" else "person"
            parts.append(f"{gender_en} character")

        if age_range:
            age_map = {
                "儿童": "child",
                "少年": "teenager",
                "青年": "young adult",
                "中年": "middle-aged",
                "老年": "elderly",
            }
            age_en = age_map.get(age_range, "")
            if age_en:
                parts.append(age_en)

        # === 外貌描写（核心！） ===
        appearance = char.get("appearance", "")
        if appearance:
            # 将中文外貌描述直接使用，AI 图片生成模型通常能理解
            parts.append(appearance)

        # === 服装 ===
        clothing = char.get("clothing", "")
        if clothing:
            parts.append(f"wearing {clothing}")

        # === 显著特征 ===
        features = char.get("distinctive_features", "")
        if features:
            parts.append(features)

        # === 性格影响表情 ===
        personality = char.get("personality", "")
        if personality:
            for key, expression in PERSONALITY_TO_EXPRESSION.items():
                if key in personality:
                    parts.append(expression)
                    break

        # === 构图 ===
        parts.extend([
            "portrait",
            "looking at viewer",
            "simple gradient background",
            "single character",
        ])

        # === 额外风格关键词 ===
        if style_keywords:
            parts.append(style_keywords)

        # === 构建最终提示词 ===
        positive_prompt = ", ".join([p for p in parts if p])

        # === 构建负面提示词 ===
        negative_parts = [COMMON_NEGATIVE_PROMPT.strip()]
        if style_config.get("negative"):
            negative_parts.append(style_config["negative"])
        negative_prompt = ", ".join(negative_parts)

        return positive_prompt, negative_prompt

    @staticmethod
    def build_location_prompt(
        location: str,
        description: str = "",
        art_style: str = "anime",
        style_keywords: str = "",
    ) -> tuple[str, str]:
        """
        构建地点背景提示词

        Args:
            location: 地点名称
            description: 场景描述
            art_style: 艺术风格
            style_keywords: 额外的风格关键词

        Returns:
            tuple: (正面提示词, 负面提示词)
        """
        style_config = ART_STYLES.get(art_style, ART_STYLES["anime"])

        parts = [
            style_config["positive"],
            f"scenery of {location}",
        ]

        if description:
            parts.append(description)

        parts.extend([
            "beautiful detailed background",
            "visual novel background",
            "atmospheric lighting",
            "no characters",
            "landscape",
        ])

        if style_keywords:
            parts.append(style_keywords)

        positive_prompt = ", ".join(parts)

        negative_parts = [
            COMMON_NEGATIVE_PROMPT.strip(),
            "characters, people, faces, text, watermark",
        ]
        if style_config.get("negative"):
            negative_parts.append(style_config["negative"])
        negative_prompt = ", ".join(negative_parts)

        return positive_prompt, negative_prompt
