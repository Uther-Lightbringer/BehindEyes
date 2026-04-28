"""
统一去重服务
支持角色和事件的三层匹配去重：别名->相似度->AI判断
"""

from typing import List, Dict, Tuple, Optional
import difflib
import logging
import json

logger = logging.getLogger(__name__)


class DeduplicationService:
    """统一去重服务"""

    # 相似度阈值
    AUTO_MERGE_THRESHOLD = 0.85      # 自动合并
    DIFFERENT_THRESHOLD = 0.5        # 视为不同
    FUZZY_RANGE = (0.5, 0.85)        # AI 判断区间

    # 效果相似度阈值
    EFFECT_SIMILARITY_THRESHOLD = 0.7

    # AI 批量判断大小
    AI_BATCH_SIZE = 20

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端，用于 AI 判断（可选）
        """
        self.llm = llm_client

    # ==================== 相似度计算 ====================

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """
        计算两个名称的相似度

        使用 difflib.SequenceMatcher 计算字符序列相似度
        """
        if not name1 or not name2:
            return 0.0
        return difflib.SequenceMatcher(None, name1, name2).ratio()

    def _calculate_effects_similarity(self, effects1: Dict, effects2: Dict) -> float:
        """
        计算两个效果字典的相似度

        使用 Jaccard 相似度比较列表类型的值
        """
        if not effects1 and not effects2:
            return 1.0
        if not effects1 or not effects2:
            return 0.0

        # 提取所有 key
        all_keys = set(effects1.keys()) | set(effects2.keys())
        if not all_keys:
            return 1.0

        similarities = []
        for key in all_keys:
            val1 = effects1.get(key, [])
            val2 = effects2.get(key, [])

            if isinstance(val1, list) and isinstance(val2, list):
                # 列表类型：计算 Jaccard 相似度
                set1, set2 = set(str(v) for v in val1), set(str(v) for v in val2)
                if not set1 and not set2:
                    similarities.append(1.0)
                elif not set1 or not set2:
                    similarities.append(0.0)
                else:
                    jaccard = len(set1 & set2) / len(set1 | set2)
                    similarities.append(jaccard)
            elif isinstance(val1, dict) and isinstance(val2, dict):
                # 嵌套字典：递归计算
                similarities.append(self._calculate_effects_similarity(val1, val2))
            else:
                # 其他类型：直接比较
                similarities.append(1.0 if val1 == val2 else 0.0)

        return sum(similarities) / len(similarities) if similarities else 0.0

    def _calculate_characters_overlap(self, chars1: List, chars2: List) -> float:
        """计算角色参与重叠度"""
        if not chars1 and not chars2:
            return 1.0
        if not chars1 or not chars2:
            return 0.0

        set1 = set(str(c) for c in chars1)
        set2 = set(str(c) for c in chars2)

        if not set1 or not set2:
            return 0.0

        return len(set1 & set2) / len(set1 | set2)
