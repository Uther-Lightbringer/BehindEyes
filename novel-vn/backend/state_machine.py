"""
状态机引擎 (v0.2)
提供游戏状态管理、事件系统、节点导航、场景生成
"""

import json
import uuid
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from db import db

logger = logging.getLogger(__name__)


# ==================== 数据类 ====================

@dataclass
class RelationState:
    """角色关系状态"""
    true_affection: int = 0  # 真实好感度
    apparent_affection: int = 0  # 表面好感度（可被欺骗）
    flags: List[str] = field(default_factory=list)  # 关系标签
    changes: List[Dict] = field(default_factory=list)  # 变化历史

    def to_dict(self) -> Dict:
        return {
            "true_affection": self.true_affection,
            "apparent_affection": self.apparent_affection,
            "flags": self.flags,
            "changes": self.changes[-10:]  # 只保留最近10条
        }


@dataclass
class GameState:
    """游戏运行时状态"""
    id: str
    novel_id: str
    user_id: str
    character_id: str
    current_node_id: str = ""
    current_route: str = "main"
    visited_nodes: List[str] = field(default_factory=list)
    choice_history: List[Dict] = field(default_factory=list)
    flags: Dict[str, Any] = field(default_factory=dict)
    relationships: Dict[str, Dict[str, RelationState]] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "novel_id": self.novel_id,
            "user_id": self.user_id,
            "character_id": self.character_id,
            "current_node_id": self.current_node_id,
            "current_route": self.current_route,
            "visited_nodes": self.visited_nodes,
            "choice_history": self.choice_history,
            "flags": self.flags,
            "relationships": {
                k: {kk: vv.to_dict() for kk, vv in v.items()}
                for k, v in self.relationships.items()
            },
            "variables": self.variables
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "GameState":
        relationships = {}
        for char_name, targets in data.get("relationships", {}).items():
            relationships[char_name] = {}
            for target_name, rel_data in targets.items():
                relationships[char_name][target_name] = RelationState(
                    true_affection=rel_data.get("true_affection", 0),
                    apparent_affection=rel_data.get("apparent_affection", 0),
                    flags=rel_data.get("flags", []),
                    changes=rel_data.get("changes", [])
                )
        return cls(
            id=data["id"],
            novel_id=data["novel_id"],
            user_id=data["user_id"],
            character_id=data["character_id"],
            current_node_id=data.get("current_node_id", ""),
            current_route=data.get("current_route", "main"),
            visited_nodes=data.get("visited_nodes", []),
            choice_history=data.get("choice_history", []),
            flags=data.get("flags", {}),
            relationships=relationships,
            variables=data.get("variables", {})
        )


# ==================== 游戏状态管理器 ====================

class GameStateManager:
    """游戏状态管理器"""

    def __init__(self):
        self._states: Dict[str, GameState] = {}

    def create_state(self, novel_id: str, user_id: str, character_id: str,
                     initial_node: str = "") -> GameState:
        """创建新的游戏状态"""
        state_id = f"state_{uuid.uuid4().hex[:12]}"
        state = GameState(
            id=state_id,
            novel_id=novel_id,
            user_id=user_id,
            character_id=character_id,
            current_node_id=initial_node
        )

        # 初始化角色关系
        characters = db.get_characters_by_novel(novel_id)
        player_char = next((c for c in characters if c["id"] == character_id), None)
        if player_char:
            player_name = player_char.get("name", "")
            for char in characters:
                if char["id"] != character_id:
                    char_name = char.get("name", "")
                    # 从数据库加载初始关系
                    rel = db.get_character_relation(novel_id, player_name, char_name)
                    if rel:
                        state.relationships[player_name] = state.relationships.get(player_name, {})
                        state.relationships[player_name][char_name] = RelationState(
                            true_affection=rel.get("current_affection", 0),
                            apparent_affection=rel.get("current_affection", 0)
                        )

        # 保存到数据库
        db.create_game_state(
            state_id=state_id,
            novel_id=novel_id,
            user_id=user_id,
            character_id=character_id,
            state_data=state.to_dict(),
            current_node=initial_node
        )

        self._states[state_id] = state
        return state

    def get_state(self, state_id: str) -> Optional[GameState]:
        """获取游戏状态"""
        if state_id in self._states:
            return self._states[state_id]

        # 从数据库加载
        state_data = db.get_game_state(state_id)
        if state_data:
            state = GameState.from_dict(state_data["state_data"])
            state.current_node_id = state_data.get("current_node", "")
            state.current_route = state_data.get("current_route", "main")
            state.visited_nodes = state_data.get("visited_nodes", [])
            state.choice_history = state_data.get("choice_history", [])
            self._states[state_id] = state
            return state

        return None

    def update_state(self, state: GameState) -> None:
        """更新游戏状态"""
        db.update_game_state(
            state_id=state.id,
            state_data=state.to_dict(),
            current_node=state.current_node_id,
            current_route=state.current_route,
            visited_nodes=state.visited_nodes,
            choice_history=state.choice_history
        )
        self._states[state.id] = state

    def delete_state(self, state_id: str) -> None:
        """删除游戏状态"""
        if state_id in self._states:
            del self._states[state_id]
        db.delete_game_state(state_id)


# ==================== 事件管理器 ====================

@dataclass
class StoryEvent:
    """故事事件"""
    id: str
    name: str
    description: str = ""
    trigger_conditions: Dict = field(default_factory=dict)
    effects: Dict = field(default_factory=dict)
    scene_data: Optional[Dict] = None


class EventManager:
    """事件管理器"""

    def __init__(self, state_manager: GameStateManager):
        self.state_manager = state_manager

    def check_and_trigger_events(self, state: GameState, node_id: str) -> List[tuple]:
        """检查并触发事件"""
        triggered = []

        events = db.get_story_events_by_novel(state.novel_id)
        node = db.get_story_node_by_node_id(state.novel_id, node_id)

        if not node:
            return triggered

        for event_data in events:
            conditions = event_data.get("trigger_conditions", {})
            if isinstance(conditions, str):
                conditions = json.loads(conditions)

            if self._check_conditions(state, conditions, node):
                event = StoryEvent(
                    id=event_data["id"],
                    name=event_data.get("name", ""),
                    description=event_data.get("description", ""),
                    trigger_conditions=conditions,
                    effects=event_data.get("effects", {}),
                    scene_data=event_data.get("scene_data")
                )
                triggered.append((event, event_data))
                self._apply_effects(state, event_data.get("effects", {}))

        return triggered

    def _check_conditions(self, state: GameState, conditions: Dict, node: Dict) -> bool:
        """检查触发条件"""
        # 检查节点条件
        if conditions.get("at_node") and conditions["at_node"] != node.get("node_id"):
            return False

        # 检查角色条件
        if conditions.get("characters_involved"):
            node_chars = set(node.get("characters_involved", []) or [])
            required_chars = set(conditions["characters_involved"])
            if not (node_chars & required_chars):
                return False

        # 检查标志条件
        if conditions.get("flags_required"):
            for flag in conditions["flags_required"]:
                if flag not in state.flags:
                    return False

        # 检查变量条件
        if conditions.get("variables"):
            for var_name, var_condition in conditions["variables"].items():
                current_value = state.variables.get(var_name, 0)
                if isinstance(var_condition, dict):
                    if var_condition.get("min") and current_value < var_condition["min"]:
                        return False
                    if var_condition.get("max") and current_value > var_condition["max"]:
                        return False
                elif current_value != var_condition:
                    return False

        return True

    def _apply_effects(self, state: GameState, effects: Dict) -> None:
        """应用事件效果"""
        if isinstance(effects, str):
            effects = json.loads(effects)

        # 设置标志
        if effects.get("set_flags"):
            for flag in effects["set_flags"]:
                state.flags[flag] = True

        # 清除标志
        if effects.get("clear_flags"):
            for flag in effects["clear_flags"]:
                state.flags.pop(flag, None)

        # 修改变量
        if effects.get("modify_variables"):
            for var_name, change in effects["modify_variables"].items():
                if var_name not in state.variables:
                    state.variables[var_name] = 0
                if isinstance(change, dict):
                    if change.get("add"):
                        state.variables[var_name] += change["add"]
                    if change.get("set") is not None:
                        state.variables[var_name] = change["set"]
                else:
                    state.variables[var_name] += change

        # 修改好感度
        if effects.get("modify_affection"):
            for target_char, change in effects["modify_affection"].items():
                # 找到玩家角色名称
                for player_name, targets in state.relationships.items():
                    if target_char in targets:
                        targets[target_char].true_affection += change
                        targets[target_char].apparent_affection += change
                        targets[target_char].changes.append({
                            "change": change,
                            "reason": "event",
                            "timestamp": datetime.utcnow().isoformat()
                        })

        self.state_manager.update_state(state)


# ==================== 节点导航器 ====================

class NodeNavigator:
    """节点导航器"""

    def __init__(self, state_manager: GameStateManager, event_manager: EventManager):
        self.state_manager = state_manager
        self.event_manager = event_manager

    def navigate_to(self, state: GameState, choice_id: str, option_index: int) -> GameState:
        """导航到下一节点"""
        node = db.get_story_node_by_node_id(state.novel_id, state.current_node_id)
        if not node:
            raise ValueError("当前节点不存在")

        choices = node.get("choices", [])
        if isinstance(choices, str):
            choices = json.loads(choices)

        if option_index >= len(choices):
            raise ValueError("选项索引无效")

        choice = choices[option_index]
        next_node_id = choice.get("next_node")

        if not next_node_id:
            raise ValueError("选项没有指定下一节点")

        # 记录选择历史
        state.choice_history.append({
            "from_node": state.current_node_id,
            "choice_id": choice_id,
            "option_index": option_index,
            "option_text": choice.get("text", ""),
            "timestamp": datetime.utcnow().isoformat()
        })

        # 更新路线
        if choice.get("route"):
            state.current_route = choice["route"]

        # 应用选择效果
        if choice.get("effects"):
            self._apply_choice_effects(state, choice["effects"])

        # 移动到下一节点
        state.visited_nodes.append(state.current_node_id)
        state.current_node_id = next_node_id

        self.state_manager.update_state(state)
        return state

    def _apply_choice_effects(self, state: GameState, effects: Dict) -> None:
        """应用选择效果"""
        # 设置标志
        if effects.get("set_flags"):
            for flag in effects["set_flags"]:
                state.flags[flag] = True

        # 修改好感度
        if effects.get("affection_change"):
            for target_char, change in effects["affection_change"].items():
                for player_name, targets in state.relationships.items():
                    if target_char in targets:
                        targets[target_char].true_affection += change
                        targets[target_char].apparent_affection += change
                        targets[target_char].changes.append({
                            "change": change,
                            "reason": "choice",
                            "timestamp": datetime.utcnow().isoformat()
                        })


# ==================== 存档管理器 ====================

class SaveManager:
    """存档管理器"""

    def __init__(self, state_manager: GameStateManager):
        self.state_manager = state_manager

    def create_save(self, game_state_id: str, save_name: str,
                    save_slot: int, play_time: int) -> str:
        """创建存档"""
        state = self.state_manager.get_state(game_state_id)
        if not state:
            raise ValueError("游戏状态不存在")

        save_id = f"save_{uuid.uuid4().hex[:12]}"
        db.create_game_save(
            save_id=save_id,
            game_state_id=game_state_id,
            save_name=save_name,
            save_slot=save_slot,
            state_snapshot=state.to_dict(),
            node_id=state.current_node_id,
            route=state.current_route,
            play_time=play_time
        )
        return save_id

    def load_save(self, save_id: str) -> Optional[GameState]:
        """加载存档"""
        save_data = db.get_game_save(save_id)
        if not save_data:
            return None

        state = GameState.from_dict(save_data["state_snapshot"])
        self.state_manager._states[state.id] = state
        return state

    def delete_save(self, save_id: str) -> None:
        """删除存档"""
        db.delete_game_save(save_id)


# ==================== 事件提取器 ====================

class EventExtractor:
    """事件提取器 - 从小说文本中提取可触发事件"""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    async def extract_events_from_segments(
        self, segments: List[Dict], characters: List[Dict],
        novel_id: str, mode: str = "auto"
    ) -> List[Dict]:
        """从片段中提取事件"""
        events = []

        if mode == "manual":
            return events

        # 角色名称列表
        char_names = [c.get("name", "") for c in characters]

        for seg in segments:
            content = seg.get("content", "")
            seg_events = await self._extract_events_from_text(content, char_names)
            for event in seg_events:
                event["id"] = f"evt_{uuid.uuid4().hex[:12]}"
                event["novel_id"] = novel_id
                events.append(event)

        return events

    async def _extract_events_from_text(self, text: str, char_names: List[str]) -> List[Dict]:
        """从文本中提取事件"""
        events = []

        if not self.llm:
            # 使用规则提取
            events = self._extract_events_with_rules(text, char_names)
        else:
            # 使用 AI 提取
            try:
                events = await self._extract_events_with_ai(text, char_names)
            except Exception as e:
                logger.warning(f"AI 事件提取失败: {e}")
                events = self._extract_events_with_rules(text, char_names)

        return events

    def _extract_events_with_rules(self, text: str, char_names: List[str]) -> List[Dict]:
        """使用规则提取事件"""
        import re
        events = []

        # 检测关键事件模式
        patterns = [
            (r"(\w+)与(\w+)(决斗|比武|较量)", "conflict"),
            (r"(\w+)发现(\w+)", "discovery"),
            (r"(\w+)救了(\w+)", "rescue"),
            (r"(\w+)背叛了(\w+)", "betrayal"),
            (r"(\w+)与(\w+)(相遇|重逢)", "meeting"),
        ]

        for pattern, event_type in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match) >= 2:
                    char_a, char_b = match[0], match[1]
                    if char_a in char_names or char_b in char_names:
                        events.append({
                            "name": f"{char_a}与{char_b}{event_type}",
                            "description": f"{char_a}和{char_b}之间发生了{event_type}",
                            "trigger_conditions": {
                                "characters_involved": [char_a, char_b]
                            },
                            "effects": {}
                        })

        return events

    async def _extract_events_with_ai(self, text: str, char_names: List[str]) -> List[Dict]:
        """使用 AI 提取事件"""
        # 简化实现，实际应该调用 LLM
        return []


# ==================== 节点构建器 ====================

class NodeBuilder:
    """节点构建器 - 从片段生成剧情节点"""

    PROMPT_BUILD_TREE = """根据以下小说片段，生成剧情节点树。

玩家角色：{player_char}
其他角色：{other_chars}

片段内容：
{content}

请以 JSON 格式返回节点列表，格式如下：
[
  {
    "node_id": "node_0",
    "route": "main",
    "parent_node": null,
    "scene_preview": "场景预览描述",
    "characters_involved": ["角色名"],
    "possible_events": [],
    "choices": [
      {
        "prompt": "选择提示",
        "options": [
          {"text": "选项文字", "next_node": "node_1", "route": "main", "effects": {}}
        ]
      }
    ]
  }
]

要求：
1. 节点代表一个独立的场景
2. 每个节点可以有多条选择分支
3. 保留原作剧情的同时增加互动性
"""

    PROMPT_GENERATE_SCENE = """生成以下场景的详细内容。

场景预览：{scene_preview}
玩家角色：{player_char}
涉及角色：{characters}
地点：{location}

{knowledge_context}

请以 JSON 格式返回场景数据：
{{
  "title": "场景标题",
  "location": "地点",
  "description": "场景描述",
  "characters": ["在场角色"],
  "dialogues": [
    {{
      "speaker": "角色名",
      "content": "对话内容",
      "emotion": "normal",
      "is_narration": false
    }}
  ]
}}
"""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    async def build_tree_from_segments(
        self, segments: List[Dict], novel_id: str,
        player_character: Dict, all_characters: List[Dict]
    ) -> List[Dict]:
        """从片段构建节点树"""
        nodes = []

        player_name = player_character.get("name", "")
        other_names = [c.get("name", "") for c in all_characters if c.get("name") != player_name]

        for i, seg in enumerate(segments):
            content = seg.get("content", "")

            if self.llm:
                try:
                    seg_nodes = await self._build_nodes_with_ai(
                        content, player_name, other_names, i
                    )
                    nodes.extend(seg_nodes)
                except Exception as e:
                    logger.warning(f"AI 构建节点失败: {e}")
                    nodes.extend(self._build_simple_nodes(content, i))
            else:
                nodes.extend(self._build_simple_nodes(content, i))

        # 链接节点
        self._link_nodes(nodes)

        # 设置节点 ID
        for node in nodes:
            node["id"] = f"node_{uuid.uuid4().hex[:12]}"

        return nodes

    async def _build_nodes_with_ai(
        self, content: str, player_char: str, other_chars: List[str], start_index: int
    ) -> List[Dict]:
        """使用 AI 构建节点"""
        prompt = self.PROMPT_BUILD_TREE.format(
            player_char=player_char,
            other_chars=", ".join(other_chars),
            content=content[:3000]
        )

        response = await self.llm.chat(prompt)
        nodes = self._parse_json_response(response)

        if nodes:
            # 调整节点 ID
            for i, node in enumerate(nodes):
                node["node_id"] = f"node_{start_index}_{i}"
            return nodes

        return self._build_simple_nodes(content, start_index)

    def _build_simple_nodes(self, content: str, index: int) -> List[Dict]:
        """构建简单节点"""
        return [{
            "node_id": f"node_{index}",
            "route": "main",
            "parent_node": f"node_{index - 1}" if index > 0 else None,
            "scene_preview": content[:200] + "...",
            "characters_involved": [],
            "possible_events": [],
            "choices": []
        }]

    def _link_nodes(self, nodes: List[Dict]) -> None:
        """链接节点"""
        for i, node in enumerate(nodes):
            if not node.get("parent_node") and i > 0:
                node["parent_node"] = nodes[i - 1].get("node_id")

            # 自动链接选择
            if not node.get("choices") and i < len(nodes) - 1:
                node["choices"] = [{
                    "prompt": "继续",
                    "options": [{
                        "text": "继续",
                        "next_node": nodes[i + 1].get("node_id"),
                        "route": "main",
                        "effects": {}
                    }]
                }]

    async def generate_node_scene(
        self, node: Dict, player_character: Dict,
        context: Dict, characters_map: Dict[str, Dict],
        knowledge_context: str = ""
    ) -> Dict:
        """生成节点场景内容"""
        player_name = player_character.get("name", "")
        characters = node.get("characters_involved", [])
        location = context.get("last_location", "未知地点")
        scene_preview = node.get("scene_preview", node.get("generation_hint", ""))

        if self.llm:
            try:
                prompt = self.PROMPT_GENERATE_SCENE.format(
                    scene_preview=scene_preview,
                    player_char=player_name,
                    characters=", ".join(characters),
                    location=location,
                    knowledge_context=f"\n【全局上下文】\n{knowledge_context}" if knowledge_context else ""
                )

                response = await self.llm.chat(prompt)
                scene = self._parse_json_response(response)

                if scene:
                    return scene
            except Exception as e:
                logger.warning(f"AI 生成场景失败: {e}")

        # 返回默认场景
        return {
            "title": scene_preview[:50] if scene_preview else "场景",
            "location": location,
            "description": scene_preview,
            "characters": characters,
            "dialogues": [{
                "speaker": "旁白",
                "content": scene_preview,
                "emotion": "normal",
                "is_narration": True
            }]
        }

    def _parse_json_response(self, response: str) -> Optional[Any]:
        """解析 JSON 响应"""
        if not response:
            return None

        try:
            return json.loads(response)
        except:
            pass

        # 尝试提取 JSON 块
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except:
                pass

        # 尝试查找数组或对象
        array_match = re.search(r'\[[\s\S]*\]', response)
        if array_match:
            try:
                return json.loads(array_match.group())
            except:
                pass

        obj_match = re.search(r'\{[\s\S]*\}', response)
        if obj_match:
            try:
                return json.loads(obj_match.group())
            except:
                pass

        return None
