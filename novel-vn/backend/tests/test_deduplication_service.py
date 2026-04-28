"""
去重服务单元测试
"""
import pytest
from services.deduplication_service import DeduplicationService


class TestSimilarityCalculation:
    """相似度计算测试"""

    def setup_method(self):
        self.service = DeduplicationService()

    def test_calculate_similarity_identical(self):
        """完全相同的名称"""
        result = self.service._calculate_similarity("李逍遥", "李逍遥")
        assert result == 1.0

    def test_calculate_similarity_similar(self):
        """相似的名称"""
        result = self.service._calculate_similarity("李逍遥", "逍遥")
        assert 0.5 < result < 1.0

    def test_calculate_similarity_different(self):
        """完全不同的名称"""
        result = self.service._calculate_similarity("李逍遥", "林月如")
        assert result < 0.5

    def test_calculate_similarity_empty(self):
        """空字符串"""
        assert self.service._calculate_similarity("", "李逍遥") == 0.0
        assert self.service._calculate_similarity("李逍遥", "") == 0.0
        assert self.service._calculate_similarity("", "") == 0.0

    def test_calculate_effects_similarity_identical(self):
        """完全相同的效果"""
        effects1 = {"set_flags": ["有宝剑", "已进城"]}
        effects2 = {"set_flags": ["有宝剑", "已进城"]}
        result = self.service._calculate_effects_similarity(effects1, effects2)
        assert result == 1.0

    def test_calculate_effects_similarity_partial(self):
        """部分重叠的效果"""
        effects1 = {"set_flags": ["有宝剑", "已进城"]}
        effects2 = {"set_flags": ["有宝剑", "见过仙灵"]}
        result = self.service._calculate_effects_similarity(effects1, effects2)
        assert 0 < result < 1.0

    def test_calculate_effects_similarity_different(self):
        """完全不同的效果"""
        effects1 = {"set_flags": ["有宝剑"]}
        effects2 = {"relationship_updates": {"李逍遥": 10}}
        result = self.service._calculate_effects_similarity(effects1, effects2)
        assert result == 0.0

    def test_calculate_effects_similarity_empty(self):
        """空效果"""
        assert self.service._calculate_effects_similarity({}, {}) == 1.0
        assert self.service._calculate_effects_similarity({"a": []}, {}) == 0.0

    def test_calculate_characters_overlap_identical(self):
        """完全相同的角色列表"""
        chars1 = ["李逍遥", "林月如", "赵灵儿"]
        chars2 = ["李逍遥", "林月如", "赵灵儿"]
        result = self.service._calculate_characters_overlap(chars1, chars2)
        assert result == 1.0

    def test_calculate_characters_overlap_partial(self):
        """部分重叠的角色列表"""
        chars1 = ["李逍遥", "林月如"]
        chars2 = ["李逍遥", "赵灵儿"]
        result = self.service._calculate_characters_overlap(chars1, chars2)
        # 交集: 李逍遥 (1), 并集: 李逍遥, 林月如, 赵灵儿 (3)
        assert result == pytest.approx(1/3, rel=0.01)

    def test_calculate_characters_overlap_different(self):
        """完全不同的角色列表"""
        chars1 = ["李逍遥", "林月如"]
        chars2 = ["王小虎", "苏媚"]
        result = self.service._calculate_characters_overlap(chars1, chars2)
        assert result == 0.0

    def test_calculate_characters_overlap_empty(self):
        """空角色列表"""
        assert self.service._calculate_characters_overlap([], []) == 1.0
        assert self.service._calculate_characters_overlap(["李逍遥"], []) == 0.0
        assert self.service._calculate_characters_overlap([], ["李逍遥"]) == 0.0
