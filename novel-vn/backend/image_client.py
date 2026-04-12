"""
图片生成客户端 - 中文 Prompt 版本
支持多种艺术风格，生成角色头像和场景背景
针对 Z-image-turbo 优化，全部使用中文提示词
"""

import os
import asyncio
import aiohttp
from typing import Optional, Dict, Any


# ============================================================
# 风格定义 - 全部使用中文
# ============================================================
ART_STYLES = {
    "anime": {
        "name": "动漫风格",
        "positive": "动漫风格, 二次元插画, 赛璐璐上色, 色彩鲜艳, 精美动漫艺术, 日本动漫风格",
        "negative": "写实风格, 照片, 三维渲染, 真实人物",
    },
    "realistic": {
        "name": "真实写真",
        "positive": "写实风格, 真实照片, 高细节, 专业人像摄影, 柔和光线, 8K画质, 电影级质感",
        "negative": "动漫, 卡通, 插画, 二次元, 素描",
    },
    "watercolor": {
        "name": "水彩插画",
        "positive": "水彩画风格, 柔和色彩, 艺术插画, 细腻笔触, 梦幻氛围, 清新淡雅",
        "negative": "写实风格, 锐利线条, 数码艺术, 动漫",
    },
    "chinese_ink": {
        "name": "古风水墨",
        "positive": "中国水墨画风格, 传统东方艺术, 优雅笔法, 简约意境, 古典美学, 国风水墨",
        "negative": "写实风格, 西方风格, 现代, 鲜艳色彩",
    },
    "comic": {
        "name": "漫画风格",
        "positive": "漫画风格, 漫画插画, 夸张表情, 动态线条, 热血漫画风, 少年漫画风格",
        "negative": "写实风格, 照片, 三维渲染",
    },
    "fantasy": {
        "name": "奇幻风格",
        "positive": "奇幻风格, 魔幻风格, 华丽装饰, 梦幻光影, 神秘氛围, 精致细节, 游戏原画质感",
        "negative": "写实风格, 现代服饰, 平淡背景",
    },
}

# 通用画质关键词 - 全部中文
QUALITY_KEYWORDS = """
杰作, 最高品质, 超高细节, 精细画面,
完美构图, 专业绘画, 大师级作品,
精美五官, 精致细节, 优雅画面
"""

# 通用负面提示词 - 全部中文
COMMON_NEGATIVE_PROMPT = """
低质量, 最差质量, 人体结构错误, 手部错误,
缺手指, 多手指, 手指变形, 裁剪,
面部崩坏, 五官畸形, 多余肢体,
文字, 水印, 签名, 模糊, 变形, 丑陋,
扭曲, 突变, 恶心, 不自然
"""

# 角色一致性关键词 - 全部中文
CONSISTENCY_KEYWORDS = """
同一角色设计, 外貌特征一致,
角色立绘, 人物设定图
"""

# 性格到表情的映射 - 全部中文
PERSONALITY_TO_EXPRESSION = {
    "活泼": "活泼开朗的表情, 灿烂笑容, 明亮的眼神",
    "开朗": "开心愉快的表情, 温暖的笑容",
    "冷酷": "冷酷的表情, 严肃的面容, 冰冷的眼神",
    "温柔": "温柔的表情, 柔和的微笑, 温暖的眼神",
    "勇敢": "自信坚定的表情, 炯炯有神的目光",
    "阴险": "阴险的表情, 狡黠的笑容",
    "傲娇": "傲娇的表情, 别扭的神态, 微微泛红的面颊",
    "高冷": "高冷的表情, 疏离的眼神, 冷漠的气质",
    "热情": "热情洋溢的表情, 明亮有神的眼睛",
    "忧郁": "忧郁的表情, 悲伤的眼神, 淡淡的哀愁",
    "邪恶": "邪恶的表情, 狰狞的笑容, 阴森的气息",
    "可爱": "可爱的表情, 天真无邪的眼神, 萌萌的感觉",
    "沉稳": "沉稳冷静的表情, 端庄的面容",
    "霸气": "霸气十足的表情, 威严的眼神, 强大的气场",
    "腹黑": "腹黑的表情, 意味深长的微笑, 深不可测的眼神",
    "狡猾": "狡猾的表情, 狡黠的微笑",
    "天真": "天真无邪的表情, 纯真的眼神, 憨厚的笑容",
    "成熟": "成熟稳重的表情, 优雅的气质, 端庄的面容",
    "狂妄": "狂妄自大的表情, 傲慢的眼神, 不可一世的样子",
    "冷静": "冷静理智的表情, 平静的眼神, 泰然自若",
    "神秘": "神秘莫测的表情, 深邃的眼神, 难以捉摸的气质",
}

# 发色映射
HAIR_COLOR_MAP = {
    "银色": "银白色头发", "金色": "金色头发", "金发": "金色头发",
    "黑色": "黑色头发", "黑发": "黑色头发", "白发": "白色头发",
    "白色": "白色头发", "红色": "红色头发", "红发": "红色头发",
    "蓝色": "蓝色头发", "蓝发": "蓝色头发", "粉色": "粉色头发",
    "粉发": "粉色头发", "紫色": "紫色头发", "紫发": "紫色头发",
    "棕色": "棕色头发", "褐色": "褐色头发", "绿色": "绿色头发",
}

# 瞳色映射
EYE_COLOR_MAP = {
    "红色": "红色眼睛", "红瞳": "红色眼睛", "红色眼眸": "红色眼睛",
    "蓝色": "蓝色眼睛", "蓝瞳": "蓝色眼睛", "蓝色眼眸": "蓝色眼睛",
    "金色": "金色眼睛", "金瞳": "金色眼睛", "金色眼眸": "金色眼睛",
    "紫色": "紫色眼睛", "紫瞳": "紫色眼睛", "紫色眼眸": "紫色眼睛",
    "绿色": "绿色眼睛", "绿瞳": "绿色眼睛", "绿色眼眸": "绿色眼睛",
    "黑色": "黑色眼睛", "黑瞳": "黑色眼睛", "黑色眼眸": "黑色眼睛",
    "银色": "银色眼睛", "银瞳": "银色眼睛",
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
    def _translate_appearance(appearance: str) -> str:
        """将外貌描述中的关键词转换为更规范的中文"""
        if not appearance:
            return ""

        result = appearance

        # 替换发色
        for key, value in HAIR_COLOR_MAP.items():
            if key in result:
                result = result.replace(key, value)

        # 替换瞳色
        for key, value in EYE_COLOR_MAP.items():
            if key in result:
                result = result.replace(key, value)

        return result

    @staticmethod
    def build_avatar_prompt(
        char: Dict[str, Any],
        art_style: str = "anime",
        style_keywords: str = "",
    ) -> tuple[str, str]:
        """
        构建角色头像提示词（全中文版本）

        Args:
            char: 角色信息字典，包含 name, gender, age_range, appearance 等
            art_style: 艺术风格 (anime/realistic/watercolor/chinese_ink/comic/fantasy)
            style_keywords: 额外的风格关键词

        Returns:
            tuple: (正面提示词, 负面提示词)
        """
        # 获取风格配置
        style_config = ART_STYLES.get(art_style, ART_STYLES["anime"])

        # 构建各部分描述
        parts = []

        # === 1. 画质关键词（最前面） ===
        parts.append(QUALITY_KEYWORDS.strip())

        # === 2. 风格关键词 ===
        parts.append(style_config["positive"])

        # === 3. 角色一致性关键词 ===
        parts.append(CONSISTENCY_KEYWORDS.strip())

        # === 4. 角色基础信息 ===
        gender = char.get("gender", "")
        age_range = char.get("age_range", "")

        # 性别和年龄
        if gender:
            gender_cn = "男性角色" if gender == "男" else "女性角色" if gender == "女" else "人物"
            parts.append(gender_cn)

        if age_range:
            age_map = {
                "儿童": "幼童",
                "少年": "少年",
                "青年": "青年",
                "中年": "中年人",
                "老年": "老年人",
            }
            age_cn = age_map.get(age_range, "")
            if age_cn:
                parts.append(age_cn)

        # === 5. 外貌描写（核心！） ===
        appearance = char.get("appearance", "")
        if appearance:
            # 转换关键词
            translated = EvolinkImageClient._translate_appearance(appearance)
            parts.append(translated)

        # === 6. 服装 ===
        clothing = char.get("clothing", "")
        if clothing:
            parts.append(f"身穿{clothing}")

        # === 7. 显著特征 ===
        features = char.get("distinctive_features", "")
        if features:
            parts.append(features)

        # === 8. 性格影响表情 ===
        personality = char.get("personality", "")
        if personality:
            expressions = []
            for key, expr in PERSONALITY_TO_EXPRESSION.items():
                if key in personality:
                    expressions.append(expr)
            if expressions:
                # 最多取2个表情描述
                parts.append(", ".join(expressions[:2]))

        # === 9. 构图关键词 ===
        parts.extend([
            "人物肖像",
            "面向观众",
            "简洁背景",
            "单人",
            "上半身",
            "立绘",
        ])

        # === 10. 额外风格关键词 ===
        if style_keywords:
            parts.append(style_keywords)

        # === 构建最终提示词 ===
        positive_prompt = ", ".join([p for p in parts if p])

        # === 构建负面提示词 ===
        negative_parts = [COMMON_NEGATIVE_PROMPT.strip()]
        if style_config.get("negative"):
            negative_parts.append(style_config["negative"])
        # 头像专属负面
        negative_parts.append("多人, 全身像, 复杂背景, 文字, 水印")
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
        构建地点背景提示词（全中文版本）

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
            QUALITY_KEYWORDS.strip(),
            style_config["positive"],
            f"{location}场景",
        ]

        if description:
            parts.append(description)

        parts.extend([
            "精美背景",
            "视觉小说背景",
            "氛围感光影",
            "无人",
            "风景",
            "场景插画",
            "细腻的环境描绘",
        ])

        if style_keywords:
            parts.append(style_keywords)

        positive_prompt = ", ".join(parts)

        negative_parts = [
            COMMON_NEGATIVE_PROMPT.strip(),
            "人物, 人脸, 文字, 水印, 签名",
        ]
        if style_config.get("negative"):
            negative_parts.append(style_config["negative"])
        negative_prompt = ", ".join(negative_parts)

        return positive_prompt, negative_prompt
