"""
知识图谱单元测试
"""
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试导入 pytest，如果不存在则使用简单的测试框架
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # 简单的测试基类
    class pytest:
        @staticmethod
        def main(args):
            pass

from knowledge_graph.models import (
    CharacterRelation,
    EventLink,
    SummaryNode,
    WorldSetting,
    KnowledgeContext,
    get_default_affection,
)


class TestCharacterRelation:
    """角色关系模型测试"""

    def test_create_relation(self):
        """测试创建关系"""
        rel = CharacterRelation(
            char_a="张三",
            char_b="李四",
            relation_type="朋友",
            current_affection=30
        )
        assert rel.char_a == "张三"
        assert rel.char_b == "李四"
        assert rel.relation_type == "朋友"
        assert rel.current_affection == 30

    def test_relation_to_dict(self):
        """测试关系转字典"""
        rel = CharacterRelation(
            char_a="A",
            char_b="B",
            relation_type="敌人",
            current_affection=-50,
            history=[{"change": -10}]
        )
        d = rel.to_dict()
        assert d["char_a"] == "A"
        assert d["char_b"] == "B"
        assert d["relation_type"] == "敌人"
        assert d["current_affection"] == -50
        assert len(d["history"]) == 1

    def test_relation_from_dict(self):
        """测试从字典创建关系"""
        data = {
            "char_a": "X",
            "char_b": "Y",
            "relation_type": "恋人",
            "current_affection": 80
        }
        rel = CharacterRelation.from_dict(data)
        assert rel.char_a == "X"
        assert rel.relation_type == "恋人"


class TestEventLink:
    """事件链模型测试"""

    def test_create_event_link(self):
        """测试创建事件链"""
        link = EventLink(
            event_id="evt_001",
            prerequisite_events=["evt_000"],
            subsequent_events=["evt_002"],
            temporal_order=1
        )
        assert link.event_id == "evt_001"
        assert len(link.prerequisite_events) == 1
        assert link.temporal_order == 1

    def test_event_link_to_dict(self):
        """测试事件链转字典"""
        link = EventLink(
            event_id="evt_test",
            mutually_exclusive=["evt_other"]
        )
        d = link.to_dict()
        assert d["event_id"] == "evt_test"
        assert "evt_other" in d["mutually_exclusive"]


class TestSummaryNode:
    """摘要节点模型测试"""

    def test_create_summary_node(self):
        """测试创建摘要节点"""
        node = SummaryNode(
            level="chapter",
            summary="这是章节摘要",
            key_characters=["张三", "李四"]
        )
        assert node.level == "chapter"
        assert node.summary == "这是章节摘要"
        assert len(node.key_characters) == 2

    def test_summary_node_with_children(self):
        """测试带子节点的摘要节点"""
        child = SummaryNode(level="section", summary="节摘要")
        parent = SummaryNode(
            level="chapter",
            summary="章摘要",
            children=[child]
        )
        assert len(parent.children) == 1
        assert parent.children[0].level == "section"


class TestWorldSetting:
    """世界设定模型测试"""

    def test_create_world_setting(self):
        """测试创建世界设定"""
        ws = WorldSetting(
            category="location",
            name="青云山",
            description="一座高耸入云的山峰"
        )
        assert ws.category == "location"
        assert ws.name == "青云山"

    def test_world_setting_with_attributes(self):
        """测试带属性的世界设定"""
        ws = WorldSetting(
            category="item",
            name="神剑",
            description="一把传说中的剑",
            attributes={"power": 100, "rarity": "legendary"}
        )
        d = ws.to_dict()
        assert d["attributes"]["power"] == 100


class TestKnowledgeContext:
    """知识上下文模型测试"""

    def test_create_empty_context(self):
        """测试创建空上下文"""
        ctx = KnowledgeContext()
        assert len(ctx.related_characters) == 0
        assert len(ctx.character_relations) == 0
        assert ctx.token_budget == 2000

    def test_context_with_data(self):
        """测试带数据的上下文"""
        ctx = KnowledgeContext(
            related_characters=[{"name": "张三"}],
            parent_summaries=["前文摘要"],
            keywords=["关键词"]
        )
        assert len(ctx.related_characters) == 1
        assert len(ctx.parent_summaries) == 1

    def test_estimate_tokens(self):
        """测试 Token 估算"""
        ctx = KnowledgeContext(
            related_characters=[{"name": "张三", "desc": "一个角色"}],
            parent_summaries=["这是一段很长的摘要" * 10]
        )
        tokens = ctx.estimate_tokens()
        assert tokens > 0


class TestGetDefaultAffection:
    """默认好感度测试"""

    def test_positive_relations(self):
        """测试正面关系"""
        assert get_default_affection("朋友") == 30
        assert get_default_affection("恋人") == 80
        assert get_default_affection("家人") == 80

    def test_negative_relations(self):
        """测试负面关系"""
        assert get_default_affection("敌人") == -50
        assert get_default_affection("死敌") == -80

    def test_unknown_relation(self):
        """测试未知关系"""
        assert get_default_affection("未知关系") == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
