"""
状态机单元测试
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试导入 pytest
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

from state_machine import (
    RelationState,
    GameState,
    GameStateManager,
)


class TestRelationState:
    """关系状态测试"""

    def test_create_relation_state(self):
        """测试创建关系状态"""
        rs = RelationState(
            true_affection=50,
            apparent_affection=40
        )
        assert rs.true_affection == 50
        assert rs.apparent_affection == 40

    def test_relation_state_to_dict(self):
        """测试关系状态转字典"""
        rs = RelationState(
            true_affection=30,
            apparent_affection=30,
            flags=["信任"],
            changes=[{"change": 10}]
        )
        d = rs.to_dict()
        assert d["true_affection"] == 30
        assert "信任" in d["flags"]


class TestGameState:
    """游戏状态测试"""

    def test_create_game_state(self):
        """测试创建游戏状态"""
        state = GameState(
            id="state_001",
            novel_id="novel_001",
            user_id="user_001",
            character_id="char_001"
        )
        assert state.id == "state_001"
        assert state.current_route == "main"
        assert len(state.visited_nodes) == 0

    def test_game_state_to_dict(self):
        """测试游戏状态转字典"""
        state = GameState(
            id="state_test",
            novel_id="novel_test",
            user_id="user_test",
            character_id="char_test",
            current_node_id="node_001",
            visited_nodes=["node_000"],
            flags={"met_protagonist": True}
        )
        d = state.to_dict()
        assert d["id"] == "state_test"
        assert d["current_node_id"] == "node_001"
        assert d["flags"]["met_protagonist"] is True

    def test_game_state_from_dict(self):
        """测试从字典创建游戏状态"""
        data = {
            "id": "state_from_dict",
            "novel_id": "novel_1",
            "user_id": "user_1",
            "character_id": "char_1",
            "current_node_id": "node_5",
            "current_route": "bad_end",
            "visited_nodes": ["node_1", "node_2"],
            "choice_history": [{"choice": 1}],
            "flags": {"secret_revealed": True},
            "relationships": {},
            "variables": {"gold": 100}
        }
        state = GameState.from_dict(data)
        assert state.id == "state_from_dict"
        assert state.current_route == "bad_end"
        assert state.variables["gold"] == 100

    def test_game_state_with_relationships(self):
        """测试带关系的游戏状态"""
        state = GameState(
            id="state_rel",
            novel_id="novel_1",
            user_id="user_1",
            character_id="char_1"
        )
        state.relationships["张三"] = {
            "李四": RelationState(true_affection=50, apparent_affection=50)
        }

        d = state.to_dict()
        assert "张三" in d["relationships"]
        assert d["relationships"]["张三"]["李四"]["true_affection"] == 50

        # 从字典恢复
        state2 = GameState.from_dict(d)
        assert "张三" in state2.relationships


class TestGameStateManager:
    """游戏状态管理器测试"""

    def test_state_storage(self):
        """测试状态存储"""
        manager = GameStateManager()
        state = GameState(
            id="state_store",
            novel_id="novel_1",
            user_id="user_1",
            character_id="char_1"
        )
        manager._states[state.id] = state

        retrieved = manager.get_state(state.id)
        assert retrieved is not None
        assert retrieved.id == state.id

    def test_get_nonexistent_state(self):
        """测试获取不存在的状态"""
        manager = GameStateManager()
        state = manager.get_state("nonexistent_id")
        assert state is None


class TestRelationStateChanges:
    """关系状态变化测试"""

    def test_affection_change(self):
        """测试好感度变化"""
        rs = RelationState(true_affection=50, apparent_affection=50)
        rs.true_affection += 10
        rs.apparent_affection += 10
        rs.changes.append({"change": 10, "reason": "帮助"})

        assert rs.true_affection == 60
        assert len(rs.changes) == 1

    def test_deceptive_affection(self):
        """测试欺骗性好感度"""
        rs = RelationState(
            true_affection=-50,  # 真实厌恶
            apparent_affection=80  # 表面友好
        )
        # 真实好感度和表面好感度可以不同
        assert rs.true_affection != rs.apparent_affection


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
